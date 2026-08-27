from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from collections.abc import Generator
from xml.sax.saxutils import escape as _xml_escape
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import re

from app import crud, schemas
from app.database import SessionLocal
from fastapi import status, Depends
from fastapi.responses import PlainTextResponse, Response

from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from app.security import create_access_token, decode_access_token
from app.config import settings
from app.storage import StorageError, store_media_bytes
import requests as _requests
from app import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

router = APIRouter(prefix="/api")

WHATSAPP_STATUS_AWAITING_ISSUE = "awaiting_issue"
WHATSAPP_STATUS_AWAITING_CITY = "awaiting_city"
WHATSAPP_STATUS_AWAITING_ADDRESS = "awaiting_address"
WHATSAPP_STATUS_AWAITING_URGENCY = "awaiting_urgency"
WHATSAPP_STATUS_AWAITING_MEDIA = "awaiting_media"
WHATSAPP_STATUS_SUBMITTED = "submitted"
WHATSAPP_STATUS_AWAITING_SCHEDULE_CONFIRMATION = "awaiting_schedule_confirmation"
WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE = "awaiting_schedule_choice"


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> schemas.UserRead:
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    email = payload.get("sub")
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    user = crud.get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def _enum_value(value: object | None) -> str | None:
    return getattr(value, "value", value)


def _normalize_whatsapp_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _derive_whatsapp_stage(service_request: models.ServiceRequest | None) -> str:
    if service_request is None or not service_request.description:
        return WHATSAPP_STATUS_AWAITING_ISSUE
    if not service_request.city:
        return WHATSAPP_STATUS_AWAITING_CITY
    if not service_request.address:
        return WHATSAPP_STATUS_AWAITING_ADDRESS
    if not service_request.urgency:
        return WHATSAPP_STATUS_AWAITING_URGENCY
    return WHATSAPP_STATUS_AWAITING_MEDIA


def _normalize_urgency(text: str | None) -> str:
    if not text:
        return "media"
    lowered = text.lower()
    if any(token in lowered for token in ("urg", "subito", "emerg", "alta")):
        return "alta"
    if any(token in lowered for token in ("bassa", "tranqu", "non urgente")):
        return "bassa"
    return "media"


def _is_skip_media_message(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return lowered in {"salta", "skip", "no", "nessuna foto", "nessun allegato"}


def _build_attachment_url(file_url: str) -> str:
    if file_url.startswith("http://") or file_url.startswith("https://"):
        return file_url
    return f"/uploads/{file_url.lstrip('/')}" if not file_url.startswith("/uploads/") else file_url


def _send_whatsapp_message(
    db: Session,
    conversation_id: int,
    phone: str | None,
    body: str,
) -> None:
    token = settings.meta_whatsapp_token
    phone_number_id = settings.meta_phone_number_id

    print("=== META WHATSAPP OUTBOUND ===")
    print("PHONE:", phone)
    print("PHONE_NUMBER_ID CONFIGURED:", bool(phone_number_id))
    print("TOKEN CONFIGURED:", bool(token))
    print("MESSAGE:", body)

    external_message_id = None

    if not token or not phone_number_id or not phone:
        print("ERROR: Meta configuration incomplete")
    else:
        normalized_phone = (
            phone
            .replace("whatsapp:", "")
            .replace("+", "")
            .strip()
        )

        url = (
            f"https://graph.facebook.com/v20.0/"
            f"{phone_number_id}/messages"
        )

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_phone,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": body,
            },
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            resp = _requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=10,
            )

            print("META STATUS:", resp.status_code)
            print("META RESPONSE:", resp.text)

            if resp.status_code in (200, 201):
                data = resp.json()
                external_message_id = data.get("messages", [{}])[0].get("id")

        except Exception as exc:
            print("META EXCEPTION:", repr(exc))

    if conversation_id > 0:
        crud.create_message(
            db,
            conversation_id=conversation_id,
            sender_type="business",
            message_type="text",
            content=body,
            external_message_id=external_message_id,
        )


def _notify_request_customer(
    db: Session,
    service_request: models.ServiceRequest | None,
    body: str,
    *,
    conversation_status: str | None = None,
) -> None:
    if not service_request or not service_request.customer_id:
        return

    customer = crud.get_customer(db, service_request.customer_id)
    if not customer or not customer.phone:
        return

    conversation = crud.get_conversation_by_customer_channel(
        db,
        service_request.business_id,
        customer.id,
        "whatsapp",
    )

    if not conversation:
        conversation = crud.create_conversation(
            db,
            service_request.business_id,
            customer.id,
            service_request.id,
            "whatsapp",
        )

    update_fields: dict[str, object] = {}
    if conversation.service_request_id != service_request.id:
        update_fields["service_request_id"] = service_request.id
    if conversation_status is not None:
        update_fields["status"] = conversation_status

    if update_fields:
        conversation = crud.update_conversation(
            db,
            conversation.id,
            **update_fields,
        ) or conversation

    _send_whatsapp_message(db, conversation.id, customer.phone, body)


def _rome_now_naive() -> datetime:
    return datetime.now(ZoneInfo("Europe/Rome")).replace(tzinfo=None)


def _format_slot(start_datetime: datetime, end_datetime: datetime) -> str:
    weekday_names = [
        "lunedi", "martedi", "mercoledi", "giovedi",
        "venerdi", "sabato", "domenica",
    ]
    weekday = weekday_names[start_datetime.weekday()]
    return (
        f"{weekday} {start_datetime.strftime('%d/%m')} "
        f"dalle {start_datetime.strftime('%H:%M')} "
        f"alle {end_datetime.strftime('%H:%M')}"
    )


def _format_alternative_message(options: list[dict[str, datetime]]) -> str:
    if not options:
        return (
            "Al momento non trovo automaticamente un altro slot libero. "
            "Scrivi PROPONGO seguito da data e ora, per esempio: "
            "PROPONGO 30/08 15:00."
        )

    lines = [
        "Nessun problema. Posso proporti questi orari:",
    ]
    for index, option in enumerate(options, start=1):
        lines.append(
            f"{index}) {_format_slot(option['start_datetime'], option['end_datetime'])}"
        )

    lines.extend([
        "",
        "Rispondi 1, 2 oppure 3 per scegliere.",
        "Oppure scrivi PROPONGO 30/08 15:00 con una tua preferenza.",
    ])
    return "\n".join(lines)


def _normalize_schedule_reply(text: str | None) -> str:
    return " ".join((text or "").strip().casefold().split())


def _is_schedule_confirmation(text: str | None) -> bool:
    normalized = _normalize_schedule_reply(text)
    return normalized in {
        "confermo", "confermato", "ok", "va bene",
        "si", "sì", "perfetto",
    }


def _is_schedule_rejection(text: str | None) -> bool:
    normalized = _normalize_schedule_reply(text)
    rejection_tokens = (
        "non disponibile",
        "non posso",
        "cambia",
        "altro orario",
        "altra data",
        "no",
    )
    return normalized in rejection_tokens or any(
        token in normalized for token in rejection_tokens[:-1]
    )


def _parse_customer_proposed_datetime(text: str | None) -> datetime | None:
    if not text:
        return None

    normalized = (
        text.strip()
        .casefold()
        .replace("alle", " ")
        .replace("ore", " ")
    )

    now = _rome_now_naive()

    relative_match = re.search(
        r"\b(domani|dopodomani)\b.*?(\d{1,2})(?:[:.](\d{2}))?",
        normalized,
    )
    if relative_match:
        day_word = relative_match.group(1)
        hour = int(relative_match.group(2))
        minute = int(relative_match.group(3) or 0)
        if hour > 23 or minute > 59:
            return None
        days = 1 if day_word == "domani" else 2
        target = now + timedelta(days=days)
        return target.replace(hour=hour, minute=minute, second=0, microsecond=0)

    match = re.search(
        r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?"
        r"\s+(?:alle\s*)?(?:ore\s*)?(\d{1,2})(?:[:.](\d{2}))?",
        normalized,
    )
    if not match:
        return None

    day = int(match.group(1))
    month = int(match.group(2))
    year_value = match.group(3)
    hour = int(match.group(4))
    minute = int(match.group(5) or 0)

    if hour > 23 or minute > 59:
        return None

    if year_value:
        year = int(year_value)
        if year < 100:
            year += 2000
    else:
        year = now.year

    try:
        candidate = datetime(year, month, day, hour, minute)
    except ValueError:
        return None

    # If the customer omitted the year and the date is already well in the past,
    # interpret it as the next calendar year.
    if not year_value and candidate < now - timedelta(days=1):
        try:
            candidate = candidate.replace(year=year + 1)
        except ValueError:
            return None

    return candidate


def _appointment_duration_minutes(
    db: Session,
    service_request: models.ServiceRequest,
    appointment: models.Appointment | None,
) -> int:
    if appointment and appointment.end_datetime > appointment.start_datetime:
        return max(
            30,
            round(
                (appointment.end_datetime - appointment.start_datetime).total_seconds()
                / 60
            ),
        )

    if service_request.estimated_duration_minutes:
        return max(30, int(service_request.estimated_duration_minutes))

    estimate = crud.estimate_service_request_duration(db, service_request)
    return max(30, int(estimate["estimated_duration_minutes"]))


def _generate_and_store_alternatives(
    db: Session,
    service_request: models.ServiceRequest,
    appointment: models.Appointment,
    *,
    not_before: datetime | None = None,
) -> list[dict[str, datetime]]:
    now = _rome_now_naive()
    duration_minutes = _appointment_duration_minutes(
        db,
        service_request,
        appointment,
    )

    anchor = not_before or max(
        now + timedelta(minutes=30),
        appointment.start_datetime + timedelta(hours=2),
    )

    options = crud.find_alternative_slots(
        db,
        business_id=service_request.business_id,
        duration_minutes=duration_minutes,
        assigned_user_id=appointment.assigned_user_id,
        exclude_appointment_id=appointment.id,
        not_before=anchor,
        excluded_starts=[appointment.start_datetime],
        count=3,
    )

    crud.save_appointment_proposal_options(
        db,
        appointment,
        options,
        created_at=now,
    )
    return options




@router.get("/products", response_model=list[schemas.ProductRead])
def read_products(db: Session = Depends(get_db)) -> list[schemas.ProductRead]:
    return crud.get_products(db)


@router.post("/products", response_model=schemas.ProductRead)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)) -> schemas.ProductRead:
    try:
        return crud.create_product(db, product)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# Customers
@router.get("/customers", response_model=list[schemas.CustomerRead])
def list_customers(db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> list[schemas.CustomerRead]:
    return crud.get_customers(db, business_id=current_user.business_id)


@router.post("/customers", response_model=schemas.CustomerRead)
def create_customer(customer: schemas.CustomerCreate, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.CustomerRead:
    try:
        payload = customer.model_copy(update={"business_id": current_user.business_id})
        return crud.create_customer(db, payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# Service requests
@router.get("/requests", response_model=list[schemas.ServiceRequestRead])
def list_requests(db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> list[schemas.ServiceRequestRead]:
    return crud.get_service_requests(db, business_id=current_user.business_id)


@router.post("/requests", response_model=schemas.ServiceRequestRead)
def create_request(req: schemas.ServiceRequestCreate, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.ServiceRequestRead:
    try:
        payload = req.model_copy(update={"business_id": current_user.business_id})
        return crud.create_service_request(db, payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/users", response_model=list[schemas.UserRead])
def list_users(db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> list[schemas.UserRead]:
    return crud.get_users(db, business_id=current_user.business_id)


@router.get("/dashboard/summary", response_model=schemas.DashboardSummary)
def dashboard_summary(db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.DashboardSummary:
    requests = crud.get_service_requests(db, business_id=current_user.business_id)
    customers = crud.get_customers(db, business_id=current_user.business_id)
    return schemas.DashboardSummary(
        new_requests=sum(1 for item in requests if _enum_value(item.status) == models.RequestStatus.NUOVA.value),
        accepted_requests=sum(1 for item in requests if _enum_value(item.status) in {models.RequestStatus.ACCETTATA.value, models.RequestStatus.PROGRAMMATA.value, models.RequestStatus.IN_CORSO.value}),
        completed_requests=sum(1 for item in requests if _enum_value(item.status) == models.RequestStatus.COMPLETATA.value),
        customer_count=len(customers),
        total_requests=len(requests),
    )


@router.get("/appointments", response_model=list[schemas.AppointmentRead])
def list_appointments(
    day: date | None = Query(None),
    assigned_user_id: int | None = Query(None),
    include_completed: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: schemas.UserRead = Depends(get_current_user),
) -> list[schemas.AppointmentRead]:
    start_datetime = None
    end_datetime = None

    if day is not None:
        start_datetime = datetime.combine(day, time.min)
        end_datetime = start_datetime + timedelta(days=1)

    return crud.get_appointments(
        db,
        business_id=current_user.business_id,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        assigned_user_id=assigned_user_id,
        include_completed=include_completed,
    )


@router.get(
    "/requests/{request_id}/duration-estimate",
    response_model=schemas.DurationEstimateRead,
)
def get_duration_estimate(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: schemas.UserRead = Depends(get_current_user),
) -> schemas.DurationEstimateRead:
    sr = crud.get_service_request(db, request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    if sr.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    estimate = crud.estimate_service_request_duration(db, sr)

    if sr.estimated_duration_minutes != estimate["estimated_duration_minutes"]:
        crud.update_service_request(
            db,
            sr.id,
            estimated_duration_minutes=estimate["estimated_duration_minutes"],
        )

    return estimate


@router.put(
    "/requests/{request_id}/location",
    response_model=schemas.ServiceRequestRead,
)
def update_request_location(
    request_id: int,
    payload: schemas.ServiceRequestLocationUpdate,
    db: Session = Depends(get_db),
    current_user: schemas.UserRead = Depends(get_current_user),
) -> schemas.ServiceRequestRead:
    sr = crud.get_service_request(db, request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    if sr.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not (-90 <= payload.latitude <= 90):
        raise HTTPException(status_code=400, detail="Invalid latitude")
    if not (-180 <= payload.longitude <= 180):
        raise HTTPException(status_code=400, detail="Invalid longitude")

    updated = crud.update_service_request(
        db,
        request_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    return updated


@router.post(
    "/requests/{request_id}/schedule",
    response_model=schemas.AppointmentRead,
)
def schedule_request(
    request_id: int,
    payload: schemas.AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: schemas.UserRead = Depends(get_current_user),
) -> schemas.AppointmentRead:
    sr = crud.get_service_request(db, request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    if sr.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    estimate = None
    duration_minutes = payload.duration_minutes

    if payload.end_datetime is None and duration_minutes is None:
        estimate = crud.estimate_service_request_duration(db, sr)
        duration_minutes = estimate["estimated_duration_minutes"]

    if payload.end_datetime is not None:
        end_datetime = payload.end_datetime
    else:
        duration_minutes = duration_minutes or 60
        if duration_minutes <= 0:
            raise HTTPException(status_code=400, detail="Duration must be positive")
        end_datetime = payload.start_datetime + timedelta(minutes=duration_minutes)

    if end_datetime <= payload.start_datetime:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    normalized = payload.model_copy(
        update={
            "end_datetime": end_datetime,
            "duration_minutes": duration_minutes,
        }
    )

    if estimate is None:
        estimated_minutes = max(
            1,
            round((end_datetime - payload.start_datetime).total_seconds() / 60),
        )
    else:
        estimated_minutes = estimate["estimated_duration_minutes"]

    crud.update_service_request(
        db,
        sr.id,
        estimated_duration_minutes=estimated_minutes,
    )
    sr = crud.get_service_request(db, sr.id)

    existing_appointment = crud.get_appointment_by_service_request(db, sr.id)
    if not crud.is_appointment_slot_available(
        db,
        business_id=sr.business_id,
        start_datetime=payload.start_datetime,
        end_datetime=end_datetime,
        assigned_user_id=(
            payload.assigned_user_id
            if payload.assigned_user_id is not None
            else sr.assigned_user_id
        ),
        exclude_appointment_id=existing_appointment.id if existing_appointment else None,
    ):
        raise HTTPException(
            status_code=409,
            detail="Lo slot selezionato si sovrappone a un altro impegno.",
        )

    appointment = crud.schedule_service_request(db, sr, normalized)

    slot_label = _format_slot(payload.start_datetime, end_datetime)
    _notify_request_customer(
        db,
        sr,
        (
            f"Ti proponiamo l'intervento {slot_label}.\n\n"
            "Rispondi CONFERMO se va bene.\n"
            "Se non sei disponibile scrivi NON DISPONIBILE e ti proporro "
            "automaticamente altri 3 orari.\n"
            "Puoi anche scrivere, per esempio: PROPONGO 30/08 15:00."
        ),
        conversation_status=WHATSAPP_STATUS_AWAITING_SCHEDULE_CONFIRMATION,
    )
    return appointment


@router.put(
    "/appointments/{appointment_id}",
    response_model=schemas.AppointmentRead,
)
def edit_appointment(
    appointment_id: int,
    payload: schemas.AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: schemas.UserRead = Depends(get_current_user),
) -> schemas.AppointmentRead:
    appointment = crud.get_appointment(db, appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appointment.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        updated = crud.update_appointment(db, appointment_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return updated


@router.get("/requests/{request_id}", response_model=schemas.ServiceRequestRead)
def get_request(request_id: int, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.ServiceRequestRead:
    sr = crud.get_service_request(db, request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    if sr.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return sr


@router.post("/requests/{request_id}/accept", response_model=schemas.ServiceRequestRead)
def accept_request(request_id: int, assigned_user_id: int | None = None, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.ServiceRequestRead:
    sr = crud.get_service_request(db, request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    if sr.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    updated = crud.accept_service_request(db, request_id, assigned_user_id=assigned_user_id)
    _notify_request_customer(db, updated, "La tua richiesta e stata presa in carico. Ti aggiorneremo a breve con la pianificazione dell'intervento.")
    return updated


@router.post("/requests/{request_id}/reject", response_model=schemas.ServiceRequestRead)
def reject_request(request_id: int, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.ServiceRequestRead:
    sr = crud.reject_service_request(db, request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    if sr.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    _notify_request_customer(db, sr, "Abbiamo esaminato la richiesta ma al momento non possiamo procedere. Se vuoi, rispondi a questo messaggio e ti ricontattiamo.")
    return sr


@router.post("/requests/{request_id}/assign", response_model=schemas.ServiceRequestRead)
def assign_request(request_id: int, assigned_user_id: int, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.ServiceRequestRead:
    sr = crud.get_service_request(db, request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    if sr.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    updated = crud.assign_service_request(db, request_id, assigned_user_id)
    assignee = crud.get_user(db, assigned_user_id)
    assignee_label = "un tecnico del team"
    if assignee:
        assignee_label = " ".join(part for part in [assignee.first_name, assignee.last_name] if part) or assignee.email
    _notify_request_customer(db, updated, f"La richiesta e stata assegnata a {assignee_label}. Ti aggiorneremo appena fissiamo l'orario dell'intervento.")
    return updated


@router.post("/requests/{request_id}/start", response_model=schemas.ServiceRequestRead)
def start_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: schemas.UserRead = Depends(get_current_user),
) -> schemas.ServiceRequestRead:
    sr = crud.get_service_request(db, request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    if sr.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    appointment = crud.get_appointment_by_service_request(db, request_id)
    if appointment and not appointment.customer_confirmed:
        raise HTTPException(
            status_code=409,
            detail="Il cliente non ha ancora confermato l'orario.",
        )

    updated = crud.start_service_request(db, request_id)
    return updated


@router.post("/requests/{request_id}/complete", response_model=schemas.ServiceRequestRead)
def complete_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: schemas.UserRead = Depends(get_current_user),
) -> schemas.ServiceRequestRead:
    sr = crud.get_service_request(db, request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    if sr.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    updated = crud.complete_service_request(db, request_id)
    _notify_request_customer(
        db,
        updated,
        "L'intervento risulta completato. Grazie per aver scelto ArtigianAI, "
        "se hai bisogno di altro puoi rispondere qui.",
    )
    return updated


# --- Auth endpoints


@router.post("/auth/register", response_model=schemas.UserRead)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)) -> schemas.UserRead:
    existing = crud.get_user_by_email(db, user.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    u = crud.create_user(db, user)
    return u


@router.post("/auth/token", response_model=schemas.Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> dict:
    user = crud.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    access_token = create_access_token({"sub": user.email})
    from app.security import create_refresh_token
    refresh_token = create_refresh_token({"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "refresh_token": refresh_token}


@router.post("/auth/login", response_model=schemas.Token)
def login_json(credentials: schemas.LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = crud.authenticate_user(db, credentials.email, credentials.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    access_token = create_access_token({"sub": user.email})
    from app.security import create_refresh_token
    refresh_token = create_refresh_token({"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "refresh_token": refresh_token}





@router.get("/auth/me", response_model=schemas.UserRead)
def read_me(current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.UserRead:
    return current_user



@router.post("/auth/refresh", response_model=schemas.Token)
def refresh_token(req: schemas.RefreshRequest, db: Session = Depends(get_db)) -> dict:
    from app.security import decode_refresh_token, create_access_token, create_refresh_token
    payload = decode_refresh_token(req.refresh_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    email = payload.get("sub")
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    user = crud.get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    access_token = create_access_token({"sub": user.email})
    # issue a new refresh token (rotating)
    new_refresh = create_refresh_token({"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "refresh_token": new_refresh}


# Attachments
@router.post("/requests/{request_id}/attachments", response_model=schemas.RequestAttachmentRead)
def upload_request_attachment(
    request_id: int,
    file: UploadFile = File(...),
    caption: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: schemas.UserRead = Depends(get_current_user),
) -> schemas.RequestAttachmentRead:
    # Authorize before writing anything to storage.
    sr = crud.get_service_request(db, request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    if sr.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this request")

    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty attachment")

    try:
        file_url = store_media_bytes(
            data=data,
            filename=file.filename or "attachment",
            content_type=file.content_type,
            folder=f"artigianai/requests/{request_id}",
        )
    except StorageError as exc:
        raise HTTPException(status_code=502, detail=f"Media storage error: {exc}")

    att = crud.create_request_attachment(
        db,
        service_request_id=request_id,
        file_url=file_url,
        file_type=file.content_type,
        caption=caption,
    )

    return {
        "id": att.id,
        "service_request_id": att.service_request_id,
        "file_url": att.file_url,
        "file_type": att.file_type,
        "caption": att.caption,
        "created_at": att.created_at.isoformat() if getattr(att, "created_at", None) is not None else None,
    }


@router.get("/requests/{request_id}/attachments", response_model=list[schemas.RequestAttachmentRead])
def list_request_attachments(request_id: int, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> list[schemas.RequestAttachmentRead]:
    atts = crud.get_request_attachments(db, service_request_id=request_id)
    out = []
    for att in atts:
        out.append({
            "id": att.id,
            "service_request_id": att.service_request_id,
            "file_url": att.file_url,
            "file_type": att.file_type,
            "caption": att.caption,
            "created_at": att.created_at.isoformat() if getattr(att, "created_at", None) is not None else None,
        })
    return out



# WhatsApp webhook verification
@router.get("/whatsapp/webhook")
def whatsapp_webhook_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    expected_token = settings.whatsapp_verify_token
    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        return PlainTextResponse(hub_challenge or "ok")
    raise HTTPException(status_code=400, detail="Invalid verification token")


@router.get("/meta/webhook")
def meta_webhook_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    expected_token = settings.meta_whatsapp_verify_token or settings.whatsapp_verify_token or settings.verify_token
    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        return PlainTextResponse(hub_challenge or "ok")
    raise HTTPException(status_code=400, detail="Invalid verification token")


def _download_meta_media(media_id: str) -> tuple[str | None, str | None]:
    import time

    token = settings.meta_whatsapp_token
    phone_number_id = settings.meta_phone_number_id

    if not token or not phone_number_id:
        print("META MEDIA ERROR: configuration incomplete")
        return None, None

    headers = {
        "Authorization": f"Bearer {token}"
    }

    # 1. Recupera la URL temporanea del media
    info_url = (
        f"https://graph.facebook.com/v20.0/{media_id}"
        f"?phone_number_id={phone_number_id}"
    )

    info_resp = _requests.get(
        info_url,
        headers=headers,
        timeout=10,
    )

    print("META MEDIA INFO STATUS:", info_resp.status_code)
    print("META MEDIA INFO:", info_resp.text)

    if info_resp.status_code != 200:
        return None, None

    info = info_resp.json()

    media_url = info.get("url")
    mime_type = info.get("mime_type", "image/jpeg")

    if not media_url:
        return None, None

    # 2. Scarica realmente l'immagine
    media_resp = _requests.get(
        media_url,
        headers=headers,
        timeout=20,
    )

    print("META MEDIA DOWNLOAD:", media_resp.status_code)

    if media_resp.status_code != 200:
        return None, None

    # 3. Salva su storage persistente (Cloudinary in staging/produzione).
    extension = ".jpg"
    if mime_type == "image/png":
        extension = ".png"
    elif mime_type == "image/webp":
        extension = ".webp"
    elif mime_type == "video/mp4":
        extension = ".mp4"

    filename = f"whatsapp_{int(time.time())}_{media_id}{extension}"

    try:
        persistent_url = store_media_bytes(
            data=media_resp.content,
            filename=filename,
            content_type=mime_type,
            folder="artigianai/whatsapp",
        )
    except StorageError as exc:
        print("META MEDIA STORAGE ERROR:", repr(exc))
        return None, None

    print("META MEDIA STORED:", persistent_url)
    return persistent_url, mime_type


def _process_whatsapp_inbound(
    db: Session,
    sender: str | None,
    body: str | None,
    media_count: int = 0,
    form: dict | None = None,
    channel: str = "twilio",
    meta_media: dict | None = None,
) -> Response:
    import sys

    def _meta_reply(message: str, conversation_id: int | None) -> Response:
        try:
            if sender:
                if conversation_id is not None:
                    _send_whatsapp_message(db, conversation_id, sender, message)
                else:
                    _send_whatsapp_message(db, -1, sender, message)
        except Exception as exc:
            print(f"ERROR sending Meta reply: {repr(exc)}", file=sys.stderr)
        return Response(status_code=200)

    def _reply(stage: str, message: str) -> Response:
        if channel == "meta":
            return _meta_reply(message, conv.id if "conv" in locals() and conv is not None else None)
        return _twilio_reply(message)

    try:
        print("\n=== WHATSAPP WEBHOOK INCOMING ===", file=sys.stderr)
        print(f"From: {sender}", file=sys.stderr)
        print(f"Body: {body}", file=sys.stderr)
        print(f"Media: {media_count}", file=sys.stderr)

        text = _normalize_whatsapp_text(body)
        if not sender:
            print("ERROR: No sender", file=sys.stderr)
            return _twilio_reply("Non ho ricevuto un mittente valido. Riprova tra un momento.")

        business_id = 1
        phone = sender.replace("whatsapp:", "").replace("+", "").strip()
        if phone and not phone.startswith("00"):
            phone = phone

        print(f"Phone: {phone}", file=sys.stderr)

        customer = None
        if phone:
            customer = crud.get_customer_by_phone(db, phone)
            print(f"Customer found: {customer.id if customer else 'NOT_FOUND'}", file=sys.stderr)
        if not customer:
            cust_data = schemas.CustomerCreate(first_name=phone, phone=phone)
            cust_data = cust_data.model_copy(update={"business_id": business_id})
            customer = crud.create_customer(db, cust_data)
            print(f"Customer created: {customer.id}", file=sys.stderr)

        conv = crud.get_conversation_by_customer_channel(db, business_id=business_id, customer_id=customer.id, channel="whatsapp")
        if not conv:
            conv = crud.create_conversation(db, business_id=business_id, customer_id=customer.id, service_request_id=None, channel="whatsapp")
            print(f"Conversation created: {conv.id}", file=sys.stderr)
        else:
            print(f"Conversation found: {conv.id}", file=sys.stderr)

        msg = crud.create_message(db, conversation_id=conv.id, sender_type="customer", message_type="text", content=text)
        print(f"Message created: {msg.id}", file=sys.stderr)

        service_request = crud.get_service_request(db, conv.service_request_id) if conv.service_request_id else None
        stage = conv.status or _derive_whatsapp_stage(service_request)
        print(f"Stage: {stage}, SR: {service_request.id if service_request else 'NONE'}", file=sys.stderr)

        if service_request is None and text:
            print("Creating new service request...", file=sys.stderr)
            service_request = crud.create_service_request(
                db,
                schemas.ServiceRequestCreate(
                    customer_id=customer.id,
                    source="whatsapp",
                    category="Nuova richiesta",
                    description=text,
                    address=customer.address,
                    city=customer.city,
                    business_id=business_id,
                ),
            )
            conv = crud.update_conversation(db, conv.id, service_request_id=service_request.id, status=WHATSAPP_STATUS_AWAITING_CITY)
            reply_msg = "Perfetto, ho registrato il problema. In quale città si trova l'intervento?"
            print(f"Returning reply: {reply_msg}", file=sys.stderr)
            return _reply(WHATSAPP_STATUS_AWAITING_CITY, reply_msg)

        if service_request is None:
            conv = crud.update_conversation(db, conv.id, status=WHATSAPP_STATUS_AWAITING_ISSUE)
            reply_msg = "Ciao! Descrivimi in una frase il problema da risolvere e ti aiuto a creare la richiesta."
            print(f"Returning reply: {reply_msg}", file=sys.stderr)
            return _reply(WHATSAPP_STATUS_AWAITING_ISSUE, reply_msg)

        stage = conv.status or _derive_whatsapp_stage(service_request)

        if stage in {
            WHATSAPP_STATUS_AWAITING_SCHEDULE_CONFIRMATION,
            WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
        }:
            appointment = crud.get_appointment_by_service_request(
                db,
                service_request.id,
            )

            if not appointment:
                conv = crud.update_conversation(
                    db,
                    conv.id,
                    status=WHATSAPP_STATUS_SUBMITTED,
                )
                return _reply(
                    WHATSAPP_STATUS_SUBMITTED,
                    "Non trovo piu una proposta di appuntamento attiva. "
                    "Il team ti ricontattera per fissare un nuovo orario.",
                )

            now = _rome_now_naive()
            duration_minutes = _appointment_duration_minutes(
                db,
                service_request,
                appointment,
            )

            proposed_start = _parse_customer_proposed_datetime(text)
            if proposed_start is not None:
                proposed_end = proposed_start + timedelta(minutes=duration_minutes)

                if proposed_start <= now:
                    return _reply(
                        stage,
                        "La data proposta deve essere futura. "
                        "Scrivi per esempio: PROPONGO 30/08 15:00.",
                    )

                if crud.is_appointment_slot_available(
                    db,
                    business_id=service_request.business_id,
                    start_datetime=proposed_start,
                    end_datetime=proposed_end,
                    assigned_user_id=appointment.assigned_user_id,
                    exclude_appointment_id=appointment.id,
                ):
                    appointment = crud.confirm_appointment_slot(
                        db,
                        appointment=appointment,
                        start_datetime=proposed_start,
                        end_datetime=proposed_end,
                    )
                    conv = crud.update_conversation(
                        db,
                        conv.id,
                        status=WHATSAPP_STATUS_SUBMITTED,
                    )
                    return _reply(
                        WHATSAPP_STATUS_SUBMITTED,
                        (
                            "Perfetto, la tua proposta e disponibile. "
                            f"Appuntamento confermato: "
                            f"{_format_slot(appointment.start_datetime, appointment.end_datetime)}."
                        ),
                    )

                options = _generate_and_store_alternatives(
                    db,
                    service_request,
                    appointment,
                    not_before=max(now + timedelta(minutes=30), proposed_start),
                )
                conv = crud.update_conversation(
                    db,
                    conv.id,
                    status=WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                )
                return _reply(
                    WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                    (
                        "L'orario che hai proposto non e disponibile.\n\n"
                        + _format_alternative_message(options)
                    ),
                )

            if stage == WHATSAPP_STATUS_AWAITING_SCHEDULE_CONFIRMATION:
                if _is_schedule_confirmation(text):
                    if crud.is_appointment_slot_available(
                        db,
                        business_id=service_request.business_id,
                        start_datetime=appointment.start_datetime,
                        end_datetime=appointment.end_datetime,
                        assigned_user_id=appointment.assigned_user_id,
                        exclude_appointment_id=appointment.id,
                    ):
                        appointment = crud.confirm_appointment_slot(
                            db,
                            appointment=appointment,
                            start_datetime=appointment.start_datetime,
                            end_datetime=appointment.end_datetime,
                        )
                        conv = crud.update_conversation(
                            db,
                            conv.id,
                            status=WHATSAPP_STATUS_SUBMITTED,
                        )
                        return _reply(
                            WHATSAPP_STATUS_SUBMITTED,
                            (
                                "Grazie, appuntamento confermato: "
                                f"{_format_slot(appointment.start_datetime, appointment.end_datetime)}."
                            ),
                        )

                    options = _generate_and_store_alternatives(
                        db,
                        service_request,
                        appointment,
                        not_before=now + timedelta(minutes=30),
                    )
                    conv = crud.update_conversation(
                        db,
                        conv.id,
                        status=WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                    )
                    return _reply(
                        WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                        (
                            "Nel frattempo quello slot non e piu disponibile.\n\n"
                            + _format_alternative_message(options)
                        ),
                    )

                if _is_schedule_rejection(text):
                    options = _generate_and_store_alternatives(
                        db,
                        service_request,
                        appointment,
                    )
                    conv = crud.update_conversation(
                        db,
                        conv.id,
                        status=WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                    )
                    return _reply(
                        WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                        _format_alternative_message(options),
                    )

                return _reply(
                    WHATSAPP_STATUS_AWAITING_SCHEDULE_CONFIRMATION,
                    (
                        "Per l'appuntamento puoi rispondere CONFERMO, "
                        "NON DISPONIBILE oppure PROPONGO 30/08 15:00."
                    ),
                )

            # Customer is choosing among automatically calculated alternatives.
            normalized = _normalize_schedule_reply(text)
            if normalized in {"1", "2", "3"}:
                options = crud.get_appointment_proposal_options(
                    appointment,
                    now=now,
                )

                if not options:
                    options = _generate_and_store_alternatives(
                        db,
                        service_request,
                        appointment,
                        not_before=now + timedelta(minutes=30),
                    )
                    return _reply(
                        WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                        (
                            "Le proposte precedenti sono scadute o non sono piu valide.\n\n"
                            + _format_alternative_message(options)
                        ),
                    )

                index = int(normalized) - 1
                if index >= len(options):
                    return _reply(
                        WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                        "Quella opzione non e disponibile. Rispondi con uno dei numeri mostrati.",
                    )

                selected_option = options[index]
                selected_start = selected_option["start_datetime"]
                selected_end = selected_option["end_datetime"]

                if not crud.is_appointment_slot_available(
                    db,
                    business_id=service_request.business_id,
                    start_datetime=selected_start,
                    end_datetime=selected_end,
                    assigned_user_id=appointment.assigned_user_id,
                    exclude_appointment_id=appointment.id,
                ):
                    options = _generate_and_store_alternatives(
                        db,
                        service_request,
                        appointment,
                        not_before=now + timedelta(minutes=30),
                    )
                    return _reply(
                        WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                        (
                            "Quello slot e stato appena occupato. "
                            "Ti propongo queste nuove disponibilita:\n\n"
                            + _format_alternative_message(options)
                        ),
                    )

                appointment = crud.confirm_appointment_slot(
                    db,
                    appointment=appointment,
                    start_datetime=selected_start,
                    end_datetime=selected_end,
                )
                conv = crud.update_conversation(
                    db,
                    conv.id,
                    status=WHATSAPP_STATUS_SUBMITTED,
                )
                return _reply(
                    WHATSAPP_STATUS_SUBMITTED,
                    (
                        "Perfetto, appuntamento confermato: "
                        f"{_format_slot(appointment.start_datetime, appointment.end_datetime)}."
                    ),
                )

            if _is_schedule_rejection(text):
                options = _generate_and_store_alternatives(
                    db,
                    service_request,
                    appointment,
                    not_before=now + timedelta(days=1),
                )
                return _reply(
                    WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                    _format_alternative_message(options),
                )

            return _reply(
                WHATSAPP_STATUS_AWAITING_SCHEDULE_CHOICE,
                (
                    "Rispondi 1, 2 oppure 3 per scegliere uno degli orari proposti, "
                    "oppure scrivi PROPONGO 30/08 15:00."
                ),
            )

        if stage == WHATSAPP_STATUS_SUBMITTED:
            if text:
                service_request = crud.create_service_request(
                    db,
                    schemas.ServiceRequestCreate(
                        customer_id=customer.id,
                        source="whatsapp",
                        category="Nuova richiesta",
                        description=text,
                        address=customer.address,
                        city=customer.city,
                        business_id=business_id,
                    ),
                )
                conv = crud.update_conversation(
                    db,
                    conv.id,
                    service_request_id=service_request.id,
                    status=WHATSAPP_STATUS_AWAITING_CITY,
                )
                return _reply(WHATSAPP_STATUS_AWAITING_CITY, "Perfetto, apro una nuova richiesta. In quale citta si trova l'intervento?")
            return _reply(WHATSAPP_STATUS_SUBMITTED, "Se vuoi aprire una nuova richiesta, descrivi in una frase il problema da risolvere.")

        if stage == WHATSAPP_STATUS_AWAITING_ISSUE and text:
            service_request = crud.update_service_request(db, service_request.id, description=text)
            conv = crud.update_conversation(db, conv.id, status=WHATSAPP_STATUS_AWAITING_CITY)
            return _reply(WHATSAPP_STATUS_AWAITING_CITY, "Ricevuto. In quale citta si trova l'intervento?")

        if stage == WHATSAPP_STATUS_AWAITING_CITY and text:
            customer = crud.patch_customer(db, customer.id, schemas.CustomerUpdate(city=text)) or customer
            service_request = crud.update_service_request(db, service_request.id, city=text)
            conv = crud.update_conversation(db, conv.id, status=WHATSAPP_STATUS_AWAITING_ADDRESS)
            return _reply(WHATSAPP_STATUS_AWAITING_ADDRESS, "Perfetto. Mandami l'indirizzo completo dove serve l'intervento.")

        if stage == WHATSAPP_STATUS_AWAITING_ADDRESS and text:
            customer = crud.patch_customer(db, customer.id, schemas.CustomerUpdate(address=text)) or customer
            service_request = crud.update_service_request(db, service_request.id, address=text)
            conv = crud.update_conversation(db, conv.id, status=WHATSAPP_STATUS_AWAITING_URGENCY)
            return _reply(WHATSAPP_STATUS_AWAITING_URGENCY, "Quanto e urgente? Puoi rispondere con: alta, media oppure bassa.")

        if stage == WHATSAPP_STATUS_AWAITING_URGENCY and text:
            urgency = _normalize_urgency(text)
            service_request = crud.update_service_request(db, service_request.id, urgency=urgency)
            conv = crud.update_conversation(db, conv.id, status=WHATSAPP_STATUS_AWAITING_MEDIA)
            return _reply(WHATSAPP_STATUS_AWAITING_MEDIA, "Se puoi, inviami ora una foto o un video del problema. Se non li hai, scrivi SALTA.")

        if stage == WHATSAPP_STATUS_AWAITING_MEDIA:

            # ===== META IMAGE =====
            if channel == "meta" and meta_media:
                media_id = meta_media.get("id")

                if media_id:
                    file_url, mime_type = _download_meta_media(media_id)

                    if file_url:
                        crud.create_request_attachment(
                            db,
                            service_request_id=service_request.id,
                            file_url=file_url,
                            file_type=mime_type,
                            caption=meta_media.get("caption") or "Foto WhatsApp",
                        )

                        conv = crud.update_conversation(
                            db,
                            conv.id,
                            status=WHATSAPP_STATUS_SUBMITTED,
                        )

                        return _reply(
                            WHATSAPP_STATUS_SUBMITTED,
                            "Perfetto \U0001F44D Ho ricevuto la foto. "
                            "La richiesta è stata registrata e il team "
                            "ti risponderà a breve."
                        )

            if media_count > 0 and form:
                for index in range(media_count):
                    media_url = form.get(f"MediaUrl{index}")
                    media_type = form.get(f"MediaContentType{index}")
                    if media_url:
                        crud.create_request_attachment(
                            db,
                            service_request_id=service_request.id,
                            file_url=media_url,
                            file_type=media_type,
                            caption="Media WhatsApp",
                        )
                conv = crud.update_conversation(db, conv.id, status=WHATSAPP_STATUS_SUBMITTED)
                return _reply(WHATSAPP_STATUS_SUBMITTED, "Perfetto, ho ricevuto anche il materiale. La tua richiesta e stata registrata: ti aggiorneremo a breve su tempi e disponibilita.")

            if _is_skip_media_message(text):
                conv = crud.update_conversation(db, conv.id, status=WHATSAPP_STATUS_SUBMITTED)
                return _reply(WHATSAPP_STATUS_SUBMITTED, "Va bene, procedo senza allegati. La richiesta e stata registrata e il team ti rispondera a breve.")

            if text:
                combined_description = (service_request.description or "").strip()
                if text not in combined_description:
                    joined = f"{combined_description}\n{text}".strip()
                    service_request = crud.update_service_request(db, service_request.id, description=joined)
                return _reply(WHATSAPP_STATUS_AWAITING_MEDIA, "Ho aggiunto questa nota alla richiesta. Se hai foto o video inviali ora, oppure scrivi SALTA.")

        conv = crud.update_conversation(db, conv.id, status=WHATSAPP_STATUS_SUBMITTED)
        status_label = _enum_value(service_request.status) or models.RequestStatus.NUOVA.value
        reply_msg = f"La tua richiesta e gia registrata con stato {status_label}. Se vuoi aggiungere dettagli, scrivili qui e li allegheremo alla pratica."
        print(f"Returning final reply: {reply_msg}", file=sys.stderr)
        return _reply(WHATSAPP_STATUS_SUBMITTED, reply_msg)
    except Exception as e:
        import traceback
        error_msg = f"ERROR in webhook: {repr(e)}\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr)
        if channel == "meta":
            return Response(status_code=200)
        return _twilio_reply("Si è verificato un errore. Riprova tra un momento.")


# Twilio WhatsApp webhook for incoming messages (Twilio Sandbox)
@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type.lower():
            payload = await request.json()
            print("META WHATSAPP JSON PAYLOAD:", payload)
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for message in value.get("messages", []):
                        sender = message.get("from")
                        message_type = message.get("type")

                        # ===== TEXT =====
                        if message_type == "text":
                            text = message.get("text", {}).get("body")

                            if sender and text:
                                return _process_whatsapp_inbound(
                                    db,
                                    f"whatsapp:{sender}",
                                    text,
                                    0,
                                    None,
                                    channel="meta",
                                )

                        # ===== IMAGE =====
                        if message_type == "image":
                            image = message.get("image", {})

                            media_id = image.get("id")
                            mime_type = image.get("mime_type")
                            caption = image.get("caption")

                            print("META IMAGE RECEIVED")
                            print("MEDIA ID:", media_id)
                            print("MIME TYPE:", mime_type)
                            print("CAPTION:", caption)

                            if sender and media_id:
                                return _process_whatsapp_inbound(
                                    db,
                                    f"whatsapp:{sender}",
                                    caption or "[Foto WhatsApp]",
                                    1,
                                    None,
                                    channel="meta",
                                    meta_media={
                                        "id": media_id,
                                        "mime_type": mime_type,
                                        "caption": caption,
                                    },
                                )
            return Response(status_code=200)

        form = await request.form()
        from_field = form.get("From") or form.get("from")
        body = form.get("Body") or form.get("body")
        media_count = int(form.get("NumMedia") or form.get("num_media") or 0)
        return _process_whatsapp_inbound(db, from_field, body, media_count, dict(form), channel="twilio")
    except Exception as e:
        import sys
        print(f"ERROR in whatsapp parsing: {repr(e)}", file=sys.stderr)
        return Response(status_code=200)


@router.post("/meta/webhook")
async def meta_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
        print("META WEBHOOK PAYLOAD:", payload)
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    sender = message.get("from")
                    message_type = message.get("type")

                    # ===== TEXT =====
                    if message_type == "text":
                        text = message.get("text", {}).get("body")

                        if sender and text:
                            return _process_whatsapp_inbound(
                                db,
                                f"whatsapp:{sender}",
                                text,
                                0,
                                None,
                                channel="meta",
                            )

                    # ===== IMAGE =====
                    if message_type == "image":
                        image = message.get("image", {})

                        media_id = image.get("id")
                        mime_type = image.get("mime_type")
                        caption = image.get("caption")

                        print("META IMAGE RECEIVED")
                        print("MEDIA ID:", media_id)
                        print("MIME TYPE:", mime_type)
                        print("CAPTION:", caption)

                        if sender and media_id:
                            return _process_whatsapp_inbound(
                                db,
                                f"whatsapp:{sender}",
                                caption or "[Foto WhatsApp]",
                                1,
                                None,
                                channel="meta",
                                meta_media={
                                    "id": media_id,
                                    "mime_type": mime_type,
                                    "caption": caption,
                                },
                            )
        return Response(status_code=200)
    except Exception as e:
        import sys
        print(f"ERROR in meta webhook parsing: {repr(e)}", file=sys.stderr)
        return Response(status_code=200)


# Customer detail/update/history endpoints (placed after auth helpers to allow Depends)


@router.get("/customers/{customer_id}", response_model=schemas.CustomerRead)
def get_customer(customer_id: int, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.CustomerRead:
    c = crud.get_customer(db, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    # ensure same business
    if c.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return c


@router.get("/customers/{customer_id}/conversation", response_model=schemas.ConversationDetail | None)
def get_customer_conversation(customer_id: int, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.ConversationDetail | None:
    customer = crud.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if customer.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    conversation = crud.get_conversation_by_customer_channel(db, current_user.business_id, customer_id, "whatsapp")
    if not conversation:
        return None
    return schemas.ConversationDetail(
        **schemas.ConversationRead.model_validate(conversation).model_dump(),
        messages=[schemas.MessageRead.model_validate(item) for item in crud.get_messages(db, conversation.id)],
    )


@router.post("/customers/{customer_id}/messages", response_model=schemas.MessageRead)
def send_customer_message(customer_id: int, payload: schemas.OutboundMessageCreate, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.MessageRead:
    customer = crud.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if customer.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    conversation = crud.get_conversation_by_customer_channel(db, current_user.business_id, customer_id, "whatsapp")
    if not conversation:
        conversation = crud.create_conversation(db, current_user.business_id, customer_id, None, "whatsapp")
    if not customer.phone:
        raise HTTPException(status_code=400, detail="Customer has no phone number")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message body is required")
    _send_whatsapp_message(db, conversation.id, customer.phone, body)
    message = crud.get_messages(db, conversation.id)[-1]
    return schemas.MessageRead.model_validate(message)


@router.put("/customers/{customer_id}", response_model=schemas.CustomerRead)
def update_customer(customer_id: int, customer: schemas.CustomerUpdate, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.CustomerRead:
    c = crud.get_customer(db, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    if c.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    updated = crud.patch_customer(db, customer_id, customer)
    if not updated:
        raise HTTPException(status_code=500, detail="Unable to update customer")
    return updated


@router.get("/customers/{customer_id}/history", response_model=schemas.CustomerHistory)
def customer_history(customer_id: int, db: Session = Depends(get_db), current_user: schemas.UserRead = Depends(get_current_user)) -> schemas.CustomerHistory:
    c = crud.get_customer(db, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    if c.business_id != current_user.business_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    hist = crud.get_customer_history(db, customer_id)
    return schemas.CustomerHistory(
        service_requests=[schemas.ServiceRequestRead.model_validate(item) for item in hist["service_requests"]],
        messages=[schemas.MessageRead.model_validate(item) for item in hist["messages"]],
    )
