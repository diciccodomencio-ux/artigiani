from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from collections.abc import Generator
from xml.sax.saxutils import escape as _xml_escape
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app import crud, schemas
from app.database import SessionLocal
from fastapi import status, Depends
from fastapi.responses import PlainTextResponse, Response

from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from app.security import create_access_token, decode_access_token
from app.config import settings
from app.storage import StorageError, store_media_bytes
import requests as _requests
import math
import re
from app import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

router = APIRouter(prefix="/api")

WHATSAPP_STATUS_AWAITING_ISSUE = "awaiting_issue"
WHATSAPP_STATUS_AWAITING_CITY = "awaiting_city"
WHATSAPP_STATUS_AWAITING_ADDRESS = "awaiting_address"
WHATSAPP_STATUS_AWAITING_URGENCY = "awaiting_urgency"
WHATSAPP_STATUS_AWAITING_MEDIA = "awaiting_media"
WHATSAPP_STATUS_SUBMITTED = "submitted"
WHATSAPP_STATUS_AWAITING_APPOINTMENT_PROPOSAL = "awaiting_appointment_proposal"


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


def _whatsapp_command(text: str | None) -> str | None:
    """Return one of NUOVA / ANNULLA / AIUTO for exact command-like messages."""
    if not text:
        return None

    candidate = text.strip().upper()
    if candidate.startswith("/"):
        candidate = candidate[1:].strip()
    candidate = candidate.rstrip(" .!?")

    aliases = {
        "NUOVA": "NUOVA",
        "NUOVO": "NUOVA",
        "NEW": "NUOVA",
        "ANNULLA": "ANNULLA",
        "CANCELLA": "ANNULLA",
        "CANCEL": "ANNULLA",
        "AIUTO": "AIUTO",
        "HELP": "AIUTO",
    }
    return aliases.get(candidate)


def _reset_whatsapp_conversation(
    db: Session,
    conversation: models.Conversation,
    *,
    status_value: str = WHATSAPP_STATUS_AWAITING_ISSUE,
) -> models.Conversation:
    """Detach the chat from the previous request and reset its intake stage.

    crud.update_conversation intentionally ignores None values, so the detach
    is done explicitly here.
    """
    conversation.service_request_id = None
    conversation.status = status_value
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _whatsapp_help_message(
    stage: str,
    service_request: models.ServiceRequest | None,
) -> str:
    status_label = (
        _enum_value(service_request.status)
        if service_request is not None
        else None
    )

    stage_help = {
        WHATSAPP_STATUS_AWAITING_ISSUE:
            "Per continuare, descrivi in una frase il problema da risolvere.",
        WHATSAPP_STATUS_AWAITING_CITY:
            "Sto aspettando la citta dell'intervento.",
        WHATSAPP_STATUS_AWAITING_ADDRESS:
            "Sto aspettando l'indirizzo completo dell'intervento.",
        WHATSAPP_STATUS_AWAITING_URGENCY:
            "Sto aspettando l'urgenza: alta, media oppure bassa.",
        WHATSAPP_STATUS_AWAITING_MEDIA:
            "Puoi inviare una foto/video del problema oppure scrivere SALTA.",
        WHATSAPP_STATUS_SUBMITTED:
            (
                f"La richiesta corrente e registrata"
                + (f" con stato {status_label}." if status_label else ".")
            ),
    }

    current_help = stage_help.get(
        stage,
        "Puoi continuare a scrivere qui per gestire la richiesta.",
    )

    return (
        f"{current_help}\n\n"
        "Comandi disponibili:\n"
        "NUOVA - avvia una nuova richiesta\n"
        "ANNULLA - annulla la richiesta corrente\n"
        "AIUTO - mostra questo messaggio"
    )



ITALY_TZ = ZoneInfo("Europe/Rome")
PLANNER_BUFFER_MINUTES = 20
PLANNER_SLOT_STEP_MINUTES = 30
PLANNER_SEARCH_DAYS = 14


def _italy_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(ITALY_TZ)


def _same_datetime_mode(local_value: datetime, reference: datetime) -> datetime:
    """Keep DB datetimes consistent with the reference datetime."""
    aware_local = (
        local_value
        if local_value.tzinfo is not None
        else local_value.replace(tzinfo=ITALY_TZ)
    )
    if reference.tzinfo is None:
        return aware_local.replace(tzinfo=None)
    return aware_local.astimezone(reference.tzinfo)


def _working_window(day_value: date) -> tuple[time, time] | None:
    # Monday-Friday
    if day_value.weekday() <= 4:
        return time(8, 0), time(19, 0)
    # Saturday
    if day_value.weekday() == 5:
        return time(8, 30), time(13, 0)
    # Sunday
    return None


def _round_up_to_slot(local_dt: datetime) -> datetime:
    minute = local_dt.minute
    step = PLANNER_SLOT_STEP_MINUTES
    rounded = ((minute + step - 1) // step) * step
    if rounded >= 60:
        local_dt = local_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        local_dt = local_dt.replace(minute=rounded, second=0, microsecond=0)
    return local_dt


def _appointment_duration(appointment: object) -> int:
    duration = getattr(appointment, "duration_minutes", None)
    if duration:
        return max(1, int(duration))
    start_dt = getattr(appointment, "start_datetime", None)
    end_dt = getattr(appointment, "end_datetime", None)
    if start_dt and end_dt:
        return max(1, round((end_dt - start_dt).total_seconds() / 60))
    return 60



def _geocode_service_request(
    db: Session,
    service_request: models.ServiceRequest,
) -> models.ServiceRequest:
    """Populate latitude/longitude from address+city when they are missing.

    Uses OpenStreetMap Nominatim as a zero-config beta fallback.
    If geocoding fails, the request is left unchanged and planning continues
    using agenda + duration only.
    """
    if (
        getattr(service_request, "latitude", None) is not None
        and getattr(service_request, "longitude", None) is not None
    ):
        return service_request

    address_parts = [
        (getattr(service_request, "address", None) or "").strip(),
        (getattr(service_request, "city", None) or "").strip(),
        "Italia",
    ]
    query = ", ".join(part for part in address_parts if part)
    if not query:
        print(f"GEO: request={service_request.id} no address to geocode")
        return service_request

    try:
        resp = _requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query,
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "it",
            },
            headers={
                "User-Agent": "ArtigianAI-Beta/1.3 geocoder",
                "Accept-Language": "it",
            },
            timeout=10,
        )

        print("GEO STATUS:", resp.status_code)
        print("GEO QUERY:", query)

        if resp.status_code != 200:
            print("GEO ERROR RESPONSE:", resp.text[:500])
            return service_request

        results = resp.json()
        if not results:
            print(f"GEO: no result for request={service_request.id}")
            return service_request

        latitude = float(results[0]["lat"])
        longitude = float(results[0]["lon"])

        updated = crud.update_service_request(
            db,
            service_request.id,
            latitude=latitude,
            longitude=longitude,
        )
        print(
            "GEO OK:",
            f"request={service_request.id}",
            f"lat={latitude}",
            f"lon={longitude}",
        )
        return updated or service_request

    except Exception as exc:
        print(
            f"GEO ERROR request={service_request.id}:",
            repr(exc),
        )
        return service_request



def _coords(service_request: object | None) -> tuple[float, float] | None:
    if service_request is None:
        return None
    lat = getattr(service_request, "latitude", None)
    lon = getattr(service_request, "longitude", None)
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    radius = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius * math.asin(min(1.0, math.sqrt(h)))


def _day_bounds(day_value: date, reference: datetime) -> tuple[datetime, datetime]:
    local_start = datetime.combine(day_value, time.min).replace(tzinfo=ITALY_TZ)
    local_end = local_start + timedelta(days=1)
    return (
        _same_datetime_mode(local_start, reference),
        _same_datetime_mode(local_end, reference),
    )


def _appointments_for_day(
    db: Session,
    business_id: int,
    day_value: date,
    reference: datetime,
    assigned_user_id: int | None = None,
) -> list:
    start_dt, end_dt = _day_bounds(day_value, reference)
    return crud.get_appointments(
        db,
        business_id=business_id,
        start_datetime=start_dt,
        end_datetime=end_dt,
        assigned_user_id=assigned_user_id,
        include_completed=False,
    )


def _slot_is_available(
    db: Session,
    business_id: int,
    assigned_user_id: int | None,
    start_dt: datetime,
    end_dt: datetime,
    exclude_appointment_id: int | None = None,
) -> bool:
    appointments = _appointments_for_day(
        db,
        business_id,
        _italy_datetime(start_dt).date(),
        start_dt,
        assigned_user_id,
    )
    buffer_delta = timedelta(minutes=PLANNER_BUFFER_MINUTES)

    for other in appointments:
        if exclude_appointment_id is not None and other.id == exclude_appointment_id:
            continue
        status_value = _enum_value(getattr(other, "status", None))
        if status_value in {"ANNULLATO", "COMPLETATO"}:
            continue
        other_start = getattr(other, "start_datetime", None)
        other_end = getattr(other, "end_datetime", None)
        if other_start is None or other_end is None:
            continue
        if start_dt < other_end + buffer_delta and end_dt > other_start - buffer_delta:
            return False
    return True


def _position_cost_for_slot(
    db: Session,
    request: models.ServiceRequest,
    start_dt: datetime,
    end_dt: datetime,
    assigned_user_id: int | None,
    exclude_appointment_id: int | None = None,
) -> float:
    """Approximate travel cost using request coordinates and adjacent jobs."""
    target = _coords(request)
    if target is None:
        return 0.0

    day_appointments = _appointments_for_day(
        db,
        request.business_id,
        _italy_datetime(start_dt).date(),
        start_dt,
        assigned_user_id,
    )

    previous = None
    following = None
    for other in day_appointments:
        if exclude_appointment_id is not None and other.id == exclude_appointment_id:
            continue
        status_value = _enum_value(getattr(other, "status", None))
        if status_value in {"ANNULLATO", "COMPLETATO"}:
            continue

        other_start = getattr(other, "start_datetime", None)
        other_end = getattr(other, "end_datetime", None)
        if other_start is None or other_end is None:
            continue

        if other_end <= start_dt:
            if previous is None or other_end > previous.end_datetime:
                previous = other
        elif other_start >= end_dt:
            if following is None or other_start < following.start_datetime:
                following = other

    cost = 0.0
    for neighbor in (previous, following):
        if neighbor is None:
            continue
        neighbor_request_id = getattr(neighbor, "service_request_id", None)
        neighbor_request = (
            crud.get_service_request(db, neighbor_request_id)
            if neighbor_request_id
            else None
        )
        neighbor_coords = _coords(neighbor_request)
        if neighbor_coords is not None:
            cost += _distance_km(target, neighbor_coords)

    return cost


def _candidate_slots(
    db: Session,
    request: models.ServiceRequest,
    duration_minutes: int,
    not_before: datetime,
    assigned_user_id: int | None = None,
    exclude_appointment_id: int | None = None,
    max_days: int = PLANNER_SEARCH_DAYS,
) -> list[tuple[float, datetime, datetime]]:
    """Generate and rank free slots by agenda, duration and position."""
    local_not_before = _italy_datetime(not_before)
    now_local = datetime.now(ITALY_TZ)
    if local_not_before.tzinfo is None:
        local_not_before = local_not_before.replace(tzinfo=ITALY_TZ)
    if local_not_before < now_local:
        local_not_before = now_local

    candidates: list[tuple[float, datetime, datetime]] = []

    for day_offset in range(max_days + 1):
        day_value = local_not_before.date() + timedelta(days=day_offset)
        window = _working_window(day_value)
        if window is None:
            continue

        open_time, close_time = window
        cursor_local = datetime.combine(day_value, open_time).replace(tzinfo=ITALY_TZ)
        close_local = datetime.combine(day_value, close_time).replace(tzinfo=ITALY_TZ)

        if day_value == local_not_before.date():
            cursor_local = max(cursor_local, _round_up_to_slot(local_not_before))

        while cursor_local + timedelta(minutes=duration_minutes) <= close_local:
            start_dt = _same_datetime_mode(cursor_local, not_before)
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            if _slot_is_available(
                db,
                request.business_id,
                assigned_user_id,
                start_dt,
                end_dt,
                exclude_appointment_id=exclude_appointment_id,
            ):
                travel_km = _position_cost_for_slot(
                    db,
                    request,
                    start_dt,
                    end_dt,
                    assigned_user_id,
                    exclude_appointment_id=exclude_appointment_id,
                )

                # Earlier days are strongly preferred. Within the same day,
                # nearby jobs and a reasonably early slot improve the score.
                minutes_after_open = int(
                    (
                        cursor_local
                        - datetime.combine(day_value, open_time).replace(tzinfo=ITALY_TZ)
                    ).total_seconds()
                    / 60
                )
                score = (
                    day_offset * 10000.0
                    + travel_km * 35.0
                    + minutes_after_open * 0.25
                )
                candidates.append((score, start_dt, end_dt))

            cursor_local += timedelta(minutes=PLANNER_SLOT_STEP_MINUTES)

    candidates.sort(key=lambda item: item[0])
    return candidates


def _best_automatic_slot(
    db: Session,
    request: models.ServiceRequest,
    duration_minutes: int,
    not_before: datetime,
    assigned_user_id: int | None = None,
    exclude_appointment_id: int | None = None,
) -> tuple[datetime, datetime] | None:
    candidates = _candidate_slots(
        db,
        request,
        duration_minutes,
        not_before,
        assigned_user_id,
        exclude_appointment_id,
    )
    return (candidates[0][1], candidates[0][2]) if candidates else None


def _best_alternative_slots(
    db: Session,
    request: models.ServiceRequest,
    appointment: object,
    max_results: int = 3,
) -> list[tuple[datetime, datetime]]:
    duration = _appointment_duration(appointment)
    now_reference = appointment.start_datetime
    if now_reference.tzinfo is None:
        not_before = datetime.now().replace(second=0, microsecond=0)
    else:
        not_before = datetime.now(ITALY_TZ).astimezone(now_reference.tzinfo)

    candidates = _candidate_slots(
        db,
        request,
        duration,
        not_before,
        getattr(appointment, "assigned_user_id", None),
        exclude_appointment_id=appointment.id,
    )

    results: list[tuple[datetime, datetime]] = []
    used_days: set[date] = set()

    # Prefer different days for the first pass.
    for _, start_dt, end_dt in candidates:
        if start_dt == appointment.start_datetime:
            continue
        day_value = _italy_datetime(start_dt).date()
        if day_value in used_days:
            continue
        results.append((start_dt, end_dt))
        used_days.add(day_value)
        if len(results) >= max_results:
            return results

    # If there are not enough distinct days, fill with same-day alternatives.
    for _, start_dt, end_dt in candidates:
        if start_dt == appointment.start_datetime:
            continue
        if any(existing[0] == start_dt for existing in results):
            continue
        results.append((start_dt, end_dt))
        if len(results) >= max_results:
            break

    return results


def _available_slots_for_day(
    db: Session,
    request: models.ServiceRequest,
    appointment: object,
    selected_day: date,
    max_results: int = 8,
) -> list[tuple[datetime, datetime]]:
    duration = _appointment_duration(appointment)
    reference = appointment.start_datetime
    window = _working_window(selected_day)
    if window is None:
        return []

    open_time, close_time = window
    cursor_local = datetime.combine(selected_day, open_time).replace(tzinfo=ITALY_TZ)
    close_local = datetime.combine(selected_day, close_time).replace(tzinfo=ITALY_TZ)

    candidates: list[tuple[float, datetime, datetime]] = []
    while cursor_local + timedelta(minutes=duration) <= close_local:
        start_dt = _same_datetime_mode(cursor_local, reference)
        end_dt = start_dt + timedelta(minutes=duration)

        if _slot_is_available(
            db,
            request.business_id,
            getattr(appointment, "assigned_user_id", None),
            start_dt,
            end_dt,
            exclude_appointment_id=appointment.id,
        ):
            travel_km = _position_cost_for_slot(
                db,
                request,
                start_dt,
                end_dt,
                getattr(appointment, "assigned_user_id", None),
                exclude_appointment_id=appointment.id,
            )
            minutes_after_open = int(
                (
                    cursor_local
                    - datetime.combine(selected_day, open_time).replace(tzinfo=ITALY_TZ)
                ).total_seconds()
                / 60
            )
            score = travel_km * 35.0 + minutes_after_open * 0.25
            candidates.append((score, start_dt, end_dt))

        cursor_local += timedelta(minutes=PLANNER_SLOT_STEP_MINUTES)

    candidates.sort(key=lambda item: item[0])
    return [(start_dt, end_dt) for _, start_dt, end_dt in candidates[:max_results]]


def _next_working_days(reference: datetime, count: int = 7) -> list[date]:
    today = max(_italy_datetime(reference).date(), datetime.now(ITALY_TZ).date())
    days: list[date] = []
    cursor = today
    while len(days) < count:
        if _working_window(cursor) is not None:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _send_whatsapp_interactive(
    db: Session,
    conversation_id: int,
    phone: str | None,
    body: str,
    interactive: dict,
) -> bool:
    token = settings.meta_whatsapp_token
    phone_number_id = settings.meta_phone_number_id
    if not token or not phone_number_id or not phone:
        print("META INTERACTIVE ERROR: configuration incomplete")
        return False

    normalized_phone = phone.replace("whatsapp:", "").replace("+", "").strip()
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalized_phone,
        "type": "interactive",
        "interactive": interactive,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = _requests.post(url, json=payload, headers=headers, timeout=10)
        print("META INTERACTIVE STATUS:", resp.status_code)
        print("META INTERACTIVE RESPONSE:", resp.text)
        if resp.status_code not in (200, 201):
            return False

        external_message_id = resp.json().get("messages", [{}])[0].get("id")
        if conversation_id > 0:
            crud.create_message(
                db,
                conversation_id=conversation_id,
                sender_type="business",
                message_type="interactive",
                content=body,
                external_message_id=external_message_id,
            )
        return True
    except Exception as exc:
        print("META INTERACTIVE EXCEPTION:", repr(exc))
        return False


def _send_whatsapp_list(
    db: Session,
    conversation_id: int,
    phone: str,
    body: str,
    button_text: str,
    rows: list[dict],
) -> bool:
    if not rows:
        return False

    interactive = {
        "type": "list",
        "body": {"text": body},
        "action": {
            "button": button_text[:20],
            "sections": [
                {
                    "title": "Disponibilità",
                    "rows": rows[:10],
                }
            ],
        },
    }
    return _send_whatsapp_interactive(
        db,
        conversation_id,
        phone,
        body,
        interactive,
    )


def _send_appointment_buttons(
    db: Session,
    service_request: models.ServiceRequest,
    appointment: object,
) -> None:
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
    if conversation.service_request_id is None:
        conversation = (
            crud.update_conversation(
                db,
                conversation.id,
                service_request_id=service_request.id,
            )
            or conversation
        )

    start_local = _italy_datetime(appointment.start_datetime)
    end_local = _italy_datetime(appointment.end_datetime)
    body = (
        "🔧 Intervento proposto automaticamente\n"
        f"📅 {start_local.strftime('%d/%m/%Y')}\n"
        f"🕒 {start_local.strftime('%H:%M')} – {end_local.strftime('%H:%M')}\n\n"
        "L'orario è stato scelto considerando agenda, durata prevista "
        "e posizione degli interventi.\n\n"
        "Seleziona una delle opzioni:"
    )

    interactive = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {
                        "id": f"appt_confirm:{appointment.id}",
                        "title": "Confermo",
                    },
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": f"appt_alternatives:{appointment.id}",
                        "title": "Altri orari",
                    },
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": f"appt_choose_day:{appointment.id}",
                        "title": "Propongo io",
                    },
                },
            ]
        },
    }

    if not _send_whatsapp_interactive(
        db,
        conversation.id,
        customer.phone,
        body,
        interactive,
    ):
        _send_whatsapp_message(
            db,
            conversation.id,
            customer.phone,
            (
                f"Intervento proposto per il "
                f"{start_local.strftime('%d/%m/%Y alle %H:%M')}, "
                f"fino alle {end_local.strftime('%H:%M')}. "
                "Rispondi CONFERMO se va bene oppure NON DISPONIBILE."
            ),
        )



def _auto_create_first_proposal(
    db: Session,
    service_request: models.ServiceRequest,
) -> object | None:
    """Create and send the first proposal without artisan intervention.

    The slot is selected from the existing agenda using:
    - estimated intervention duration;
    - currently occupied appointments;
    - geographic position when latitude/longitude are already available.
    """
    existing = crud.get_appointment_by_service_request(db, service_request.id)
    if existing is not None:
        return existing

    estimate = crud.estimate_service_request_duration(db, service_request)
    duration_minutes = max(
        1,
        int(estimate.get("estimated_duration_minutes") or 60),
    )

    crud.update_service_request(
        db,
        service_request.id,
        estimated_duration_minutes=duration_minutes,
    )
    service_request = crud.get_service_request(db, service_request.id)

    # Geolocate the textual address before scoring candidate slots.
    # If geocoding fails, planning still continues using agenda + duration.
    service_request = _geocode_service_request(
        db,
        service_request,
    )

    # Use local-naive time because the existing planner/database currently
    # stores appointment times in local wall-clock convention.
    not_before = datetime.now(ITALY_TZ).replace(
        tzinfo=None,
        second=0,
        microsecond=0,
    )

    best_slot = _best_automatic_slot(
        db,
        service_request,
        duration_minutes,
        not_before,
        getattr(service_request, "assigned_user_id", None),
    )
    if best_slot is None:
        print(
            f"AUTO PLAN: no slot found for request {service_request.id}"
        )
        return None

    automatic_start, automatic_end = best_slot

    payload = schemas.AppointmentCreate(
        start_datetime=automatic_start,
        end_datetime=automatic_end,
        duration_minutes=duration_minutes,
        assigned_user_id=getattr(
            service_request,
            "assigned_user_id",
            None,
        ),
        notes="Prima proposta generata automaticamente da ArtigianAI",
    )

    appointment = crud.schedule_service_request(
        db,
        service_request,
        payload,
    )

    try:
        appointment = crud.update_appointment(
            db,
            appointment.id,
            schemas.AppointmentUpdate(
                status=models.AppointmentStatus.PROPOSTO.value,
                customer_confirmed=False,
            ),
        )
    except Exception as exc:
        print("AUTO PLAN appointment state warning:", repr(exc))

    print(
        "AUTO PLAN:",
        f"request={service_request.id}",
        f"appointment={appointment.id}",
        f"start={appointment.start_datetime}",
        f"end={appointment.end_datetime}",
        f"duration={duration_minutes}",
    )

    _send_appointment_buttons(
        db,
        service_request,
        appointment,
    )
    return appointment


def _finish_intake_with_auto_proposal(
    db: Session,
    conversation: models.Conversation,
    service_request: models.ServiceRequest,
    channel: str,
) -> Response:
    """Finish intake and immediately let the planner propose the best slot."""
    crud.update_conversation(
        db,
        conversation.id,
        status=WHATSAPP_STATUS_SUBMITTED,
    )

    try:
        appointment = _auto_create_first_proposal(
            db,
            service_request,
        )
    except Exception as exc:
        print("AUTO PLAN ERROR:", repr(exc))
        appointment = None

    if appointment is not None:
        # _send_appointment_buttons already sent the user-facing proposal.
        return Response(status_code=200)

    # Safe fallback: keep the request registered even when no automatic slot
    # can be generated.
    if channel == "meta":
        _send_whatsapp_message(
            db,
            conversation.id,
            crud.get_customer(db, service_request.customer_id).phone,
            (
                "✅ Richiesta registrata. Al momento non trovo uno slot "
                "automatico disponibile; ti aggiorneremo appena possibile."
            ),
        )
        return Response(status_code=200)

    return _twilio_reply(
        "Richiesta registrata. Al momento non trovo uno slot automatico disponibile."
    )



def _confirm_appointment(
    db: Session,
    appointment: object,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
) -> object:
    update_data = {
        "status": models.AppointmentStatus.CONFERMATO.value,
    }
    if start_dt is not None:
        update_data["start_datetime"] = start_dt
    if end_dt is not None:
        update_data["end_datetime"] = end_dt
        update_data["duration_minutes"] = max(
            1,
            round(
                (
                    end_dt
                    - (start_dt if start_dt is not None else appointment.start_datetime)
                ).total_seconds()
                / 60
            ),
        )

    try:
        payload = schemas.AppointmentUpdate(
            **update_data,
            customer_confirmed=True,
        )
    except Exception:
        payload = schemas.AppointmentUpdate(**update_data)

    return crud.update_appointment(db, appointment.id, payload)


def _extract_meta_interaction(message: dict) -> str | None:
    if message.get("type") != "interactive":
        return None
    interactive = message.get("interactive", {})
    if interactive.get("type") == "button_reply":
        return interactive.get("button_reply", {}).get("id")
    if interactive.get("type") == "list_reply":
        return interactive.get("list_reply", {}).get("id")
    return None


def _handle_appointment_interaction(
    db: Session,
    sender: str | None,
    interaction_id: str,
) -> Response:
    if not sender:
        return Response(status_code=200)

    phone = sender.replace("whatsapp:", "").replace("+", "").strip()
    customer = crud.get_customer_by_phone(db, phone)
    if not customer:
        return Response(status_code=200)

    conversation = crud.get_conversation_by_customer_channel(
        db,
        1,
        customer.id,
        "whatsapp",
    )
    if not conversation:
        return Response(status_code=200)

    def reply(message: str) -> Response:
        _send_whatsapp_message(
            db,
            conversation.id,
            customer.phone,
            message,
        )
        return Response(status_code=200)

    try:
        action, raw_value = interaction_id.split(":", 1)
    except ValueError:
        return reply("Scelta non riconosciuta. Riprova dal messaggio dell'appuntamento.")

    if action in {"appt_confirm", "appt_alternatives", "appt_choose_day"}:
        try:
            appointment_id = int(raw_value)
        except ValueError:
            return reply("Appuntamento non valido.")

        appointment = crud.get_appointment(db, appointment_id)
        if not appointment:
            return reply("Non trovo più questo appuntamento.")

        request_id = getattr(appointment, "service_request_id", None)
        request = crud.get_service_request(db, request_id) if request_id else None
        if not request or request.customer_id != customer.id:
            return reply("Questo appuntamento non appartiene alla richiesta corrente.")

        if (
            conversation.service_request_id is not None
            and conversation.service_request_id != request.id
        ):
            return reply(
                "Questa proposta non è più quella attiva. "
                "Usa l'ultimo messaggio ricevuto."
            )

        if action == "appt_confirm":
            if not _slot_is_available(
                db,
                request.business_id,
                getattr(appointment, "assigned_user_id", None),
                appointment.start_datetime,
                appointment.end_datetime,
                exclude_appointment_id=appointment.id,
            ):
                return reply(
                    "Questo orario non è più disponibile. "
                    "Seleziona Altri orari."
                )

            updated = _confirm_appointment(db, appointment)
            start_local = _italy_datetime(updated.start_datetime)
            end_local = _italy_datetime(updated.end_datetime)
            return reply(
                "✅ Appuntamento confermato\n"
                f"📅 {start_local.strftime('%d/%m/%Y')}\n"
                f"🕒 {start_local.strftime('%H:%M')} – "
                f"{end_local.strftime('%H:%M')}"
            )

        if action == "appt_alternatives":
            alternatives = _best_alternative_slots(
                db,
                request,
                appointment,
                max_results=3,
            )
            if not alternatives:
                return reply(
                    "Non trovo altri orari disponibili nei prossimi giorni. "
                    "Seleziona Propongo io."
                )

            rows = []
            for start_dt, end_dt in alternatives:
                start_local = _italy_datetime(start_dt)
                end_local = _italy_datetime(end_dt)
                rows.append(
                    {
                        "id": f"appt_slot:{appointment.id}|{start_dt.isoformat()}",
                        "title": start_local.strftime("%d/%m · %H:%M"),
                        "description": f"fino alle {end_local.strftime('%H:%M')}",
                    }
                )

            if _send_whatsapp_list(
                db,
                conversation.id,
                customer.phone,
                "🔄 Ecco le migliori alternative disponibili:",
                "Scegli orario",
                rows,
            ):
                return Response(status_code=200)

            return reply("Non riesco a mostrare le alternative. Riprova tra poco.")

        days = _next_working_days(appointment.start_datetime, count=7)
        rows = [
            {
                "id": f"appt_day:{appointment.id}|{day_value.isoformat()}",
                "title": day_value.strftime("%d/%m/%Y"),
                "description": "Mostra gli orari disponibili",
            }
            for day_value in days
        ]

        if _send_whatsapp_list(
            db,
            conversation.id,
            customer.phone,
            "📅 Scegli il giorno che preferisci:",
            "Scegli giorno",
            rows,
        ):
            return Response(status_code=200)

        return reply("Non riesco a mostrare i giorni disponibili. Riprova tra poco.")

    if action in {"appt_day", "appt_slot"}:
        try:
            appointment_id_text, encoded_value = raw_value.split("|", 1)
            appointment_id = int(appointment_id_text)
        except ValueError:
            return reply("Scelta non valida.")

        appointment = crud.get_appointment(db, appointment_id)
        if not appointment:
            return reply("Non trovo più questo appuntamento.")

        request_id = getattr(appointment, "service_request_id", None)
        request = crud.get_service_request(db, request_id) if request_id else None
        if not request or request.customer_id != customer.id:
            return reply("Questo appuntamento non appartiene alla richiesta corrente.")

        if action == "appt_day":
            try:
                selected_day = date.fromisoformat(encoded_value)
            except ValueError:
                return reply("Giorno non valido.")

            slots = _available_slots_for_day(
                db,
                request,
                appointment,
                selected_day,
                max_results=8,
            )
            if not slots:
                return reply(
                    "Non ci sono orari disponibili in quel giorno. "
                    "Seleziona Propongo io e scegli un altro giorno."
                )

            rows = []
            for start_dt, end_dt in slots:
                start_local = _italy_datetime(start_dt)
                end_local = _italy_datetime(end_dt)
                rows.append(
                    {
                        "id": f"appt_slot:{appointment.id}|{start_dt.isoformat()}",
                        "title": start_local.strftime("%H:%M"),
                        "description": f"fino alle {end_local.strftime('%H:%M')}",
                    }
                )

            if _send_whatsapp_list(
                db,
                conversation.id,
                customer.phone,
                f"Orari disponibili per il {selected_day.strftime('%d/%m/%Y')}:",
                "Scegli orario",
                rows,
            ):
                return Response(status_code=200)

            return reply("Non riesco a mostrare gli orari. Riprova tra poco.")

        try:
            selected_start = datetime.fromisoformat(encoded_value)
        except ValueError:
            return reply("Orario non valido.")

        duration = _appointment_duration(appointment)
        selected_end = selected_start + timedelta(minutes=duration)

        if not _slot_is_available(
            db,
            request.business_id,
            getattr(appointment, "assigned_user_id", None),
            selected_start,
            selected_end,
            exclude_appointment_id=appointment.id,
        ):
            return reply(
                "Questo orario è stato appena occupato. "
                "Seleziona di nuovo Altri orari o Propongo io."
            )

        updated = _confirm_appointment(
            db,
            appointment,
            start_dt=selected_start,
            end_dt=selected_end,
        )
        start_local = _italy_datetime(updated.start_datetime)
        end_local = _italy_datetime(updated.end_datetime)

        return reply(
            "✅ Nuovo appuntamento confermato\n"
            f"📅 {start_local.strftime('%d/%m/%Y')}\n"
            f"🕒 {start_local.strftime('%H:%M')} – "
            f"{end_local.strftime('%H:%M')}\n\n"
            "La pianificazione è stata aggiornata."
        )

    return reply("Scelta non riconosciuta.")


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


def _notify_request_customer(db: Session, service_request: models.ServiceRequest | None, body: str) -> None:
    if not service_request or not service_request.customer_id:
        return
    customer = crud.get_customer(db, service_request.customer_id)
    if not customer or not customer.phone:
        return
    conversation = crud.get_conversation_by_customer_channel(db, service_request.business_id, customer.id, "whatsapp")
    if not conversation:
        conversation = crud.create_conversation(db, service_request.business_id, customer.id, service_request.id, "whatsapp")
    if conversation.service_request_id is None:
        conversation = crud.update_conversation(db, conversation.id, service_request_id=service_request.id) or conversation
    _send_whatsapp_message(db, conversation.id, customer.phone, body)




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

    # The duration represents the difficulty/complexity estimate.
    # A manual duration selected in the app remains an explicit override.
    estimate = crud.estimate_service_request_duration(db, sr)
    estimated_minutes = int(estimate["estimated_duration_minutes"])
    duration_minutes = payload.duration_minutes or estimated_minutes
    if duration_minutes <= 0:
        raise HTTPException(status_code=400, detail="Duration must be positive")

    crud.update_service_request(
        db,
        sr.id,
        estimated_duration_minutes=estimated_minutes,
    )
    sr = crud.get_service_request(db, sr.id)

    # The date/time sent by the frontend is treated as "not before".
    # The actual first proposal is selected automatically using:
    # agenda availability + intervention duration + geographic position.
    best_slot = _best_automatic_slot(
        db,
        sr,
        duration_minutes,
        payload.start_datetime,
        getattr(sr, "assigned_user_id", None),
    )
    if best_slot is None:
        raise HTTPException(
            status_code=409,
            detail="Nessuno slot disponibile nei prossimi 14 giorni.",
        )

    automatic_start, automatic_end = best_slot
    normalized = payload.model_copy(
        update={
            "start_datetime": automatic_start,
            "end_datetime": automatic_end,
            "duration_minutes": duration_minutes,
        }
    )

    appointment = crud.schedule_service_request(db, sr, normalized)

    # Keep the appointment waiting for the customer's confirmation when the
    # schema/model supports this field.
    try:
        appointment = crud.update_appointment(
            db,
            appointment.id,
            schemas.AppointmentUpdate(
                status=models.AppointmentStatus.PROPOSTO.value,
                customer_confirmed=False,
            ),
        )
    except Exception:
        pass

    _send_appointment_buttons(db, sr, appointment)
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

        command = _whatsapp_command(text)
        if command:
            print(f"WHATSAPP COMMAND: {command}", file=sys.stderr)

        if command == "AIUTO":
            return _reply(
                stage,
                _whatsapp_help_message(stage, service_request),
            )

        if command == "NUOVA":
            previous_request_id = service_request.id if service_request else None
            previous_status = (
                _enum_value(service_request.status)
                if service_request is not None
                else None
            )

            conv = _reset_whatsapp_conversation(db, conv)

            if previous_request_id is not None:
                return _reply(
                    WHATSAPP_STATUS_AWAITING_ISSUE,
                    (
                        f"Va bene. La richiesta #{previous_request_id} resta registrata"
                        + (f" con stato {previous_status}." if previous_status else ".")
                        + "\nOra descrivi in una frase il nuovo problema."
                    ),
                )

            return _reply(
                WHATSAPP_STATUS_AWAITING_ISSUE,
                "Va bene. Descrivi in una frase il nuovo problema da risolvere.",
            )

        if command == "ANNULLA":
            if service_request is None:
                conv = _reset_whatsapp_conversation(db, conv)
                return _reply(
                    WHATSAPP_STATUS_AWAITING_ISSUE,
                    "Non c'e una richiesta attiva da annullare. Se vuoi iniziarne una, descrivi il problema oppure scrivi NUOVA.",
                )

            current_status = _enum_value(service_request.status)
            final_statuses = {
                models.RequestStatus.COMPLETATA.value,
                models.RequestStatus.RIFIUTATA.value,
                models.RequestStatus.ANNULLATA.value,
            }

            if current_status == models.RequestStatus.IN_CORSO.value:
                return _reply(
                    stage,
                    (
                        f"La richiesta #{service_request.id} e gia IN_CORSO e non puo essere annullata automaticamente. "
                        "Contatta direttamente l'artigiano per interrompere l'intervento."
                    ),
                )

            if current_status in final_statuses:
                request_id = service_request.id
                conv = _reset_whatsapp_conversation(db, conv)
                return _reply(
                    WHATSAPP_STATUS_AWAITING_ISSUE,
                    (
                        f"La richiesta #{request_id} e gia nello stato {current_status} e non richiede annullamento. "
                        "Per una nuova richiesta descrivi il problema oppure scrivi NUOVA."
                    ),
                )

            request_id = service_request.id
            crud.update_service_request(
                db,
                request_id,
                status=models.RequestStatus.ANNULLATA,
            )

            # If the request had already been scheduled, remove the appointment
            # from the active planner as well.
            try:
                appointment = crud.get_appointment_by_service_request(db, request_id)
                if appointment:
                    appointment_status = _enum_value(appointment.status)
                    if appointment_status not in {
                        models.AppointmentStatus.COMPLETATO.value,
                        models.AppointmentStatus.ANNULLATO.value,
                    }:
                        crud.update_appointment(
                            db,
                            appointment.id,
                            schemas.AppointmentUpdate(
                                status=models.AppointmentStatus.ANNULLATO.value
                            ),
                        )
            except Exception as exc:
                # The cancellation of the service request must still succeed even
                # if an old deployment has no planner helper available.
                print(
                    f"WARNING cancelling appointment for SR {request_id}: {repr(exc)}",
                    file=sys.stderr,
                )

            conv = _reset_whatsapp_conversation(db, conv)
            return _reply(
                WHATSAPP_STATUS_AWAITING_ISSUE,
                (
                    f"Richiesta #{request_id} annullata. "
                    "Se hai un altro problema, descrivilo qui oppure scrivi NUOVA."
                ),
            )

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
            reply_msg = (
                "Ciao! Descrivimi in una frase il problema da risolvere e ti aiuto a creare la richiesta. "
                "In qualsiasi momento puoi scrivere AIUTO."
            )
            print(f"Returning reply: {reply_msg}", file=sys.stderr)
            return _reply(WHATSAPP_STATUS_AWAITING_ISSUE, reply_msg)

        stage = conv.status or _derive_whatsapp_stage(service_request)

        if stage == WHATSAPP_STATUS_AWAITING_APPOINTMENT_PROPOSAL:
            if service_request is None:
                conv = crud.update_conversation(
                    db,
                    conv.id,
                    status=WHATSAPP_STATUS_SUBMITTED,
                )
                return _reply(
                    WHATSAPP_STATUS_SUBMITTED,
                    "Non trovo la richiesta collegata all'appuntamento.",
                )

            appointment = crud.get_appointment_by_service_request(
                db,
                service_request.id,
            )
            if appointment is None:
                conv = crud.update_conversation(
                    db,
                    conv.id,
                    status=WHATSAPP_STATUS_SUBMITTED,
                )
                return _reply(
                    WHATSAPP_STATUS_SUBMITTED,
                    "Non trovo un appuntamento programmato per questa richiesta.",
                )

            proposed_start = _parse_customer_proposed_datetime(
                text or "",
                appointment.start_datetime,
            )
            if proposed_start is None:
                return _reply(
                    WHATSAPP_STATUS_AWAITING_APPOINTMENT_PROPOSAL,
                    "Formato non riconosciuto. Usa il pulsante Propongo io per scegliere "
                    "giorno e orario dalle liste disponibili.",
                )

            updated_appointment = _update_customer_proposed_appointment(
                db,
                appointment,
                proposed_start,
            )
            conv = crud.update_conversation(
                db,
                conv.id,
                status=WHATSAPP_STATUS_SUBMITTED,
            )

            start_local = _italy_datetime(updated_appointment.start_datetime)
            end_local = _italy_datetime(updated_appointment.end_datetime)

            return _reply(
                WHATSAPP_STATUS_SUBMITTED,
                "✅ Nuovo appuntamento confermato\n"
                f"📅 {start_local.strftime('%d/%m/%Y')}\n"
                f"🕒 {start_local.strftime('%H:%M')} – "
                f"{end_local.strftime('%H:%M')}\n\n"
                "La pianificazione è stata aggiornata.",
            )

        if stage == WHATSAPP_STATUS_SUBMITTED:
            status_label = _enum_value(service_request.status) or models.RequestStatus.NUOVA.value
            return _reply(
                WHATSAPP_STATUS_SUBMITTED,
                (
                    f"La richiesta #{service_request.id} e gia registrata con stato {status_label}. "
                    "Per aprire una nuova richiesta scrivi NUOVA. "
                    "Per annullare quella corrente scrivi ANNULLA. "
                    "Per vedere i comandi scrivi AIUTO."
                ),
            )

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

                        return _finish_intake_with_auto_proposal(
                            db,
                            conv,
                            service_request,
                            channel,
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
                return _finish_intake_with_auto_proposal(
                    db,
                    conv,
                    service_request,
                    channel,
                )

            if _is_skip_media_message(text):
                return _finish_intake_with_auto_proposal(
                    db,
                    conv,
                    service_request,
                    channel,
                )

            if text:
                combined_description = (service_request.description or "").strip()
                if text not in combined_description:
                    joined = f"{combined_description}\n{text}".strip()
                    service_request = crud.update_service_request(db, service_request.id, description=joined)
                return _reply(
                    WHATSAPP_STATUS_AWAITING_MEDIA,
                    (
                        "Ho aggiunto questa nota alla richiesta. "
                        "Se hai foto o video inviali ora, oppure scrivi SALTA. "
                        "Se invece vuoi aprire un'altra richiesta, scrivi NUOVA."
                    ),
                )

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

                        # ===== INTERACTIVE BUTTON / LIST =====
                        interaction_id = _extract_meta_interaction(message)
                        if sender and interaction_id:
                            return _handle_appointment_interaction(db, f"whatsapp:{sender}", interaction_id)

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

                    # ===== INTERACTIVE BUTTON / LIST =====
                    interaction_id = _extract_meta_interaction(message)
                    if sender and interaction_id:
                        return _handle_appointment_interaction(db, f"whatsapp:{sender}", interaction_id)

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
