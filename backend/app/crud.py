from sqlalchemy.orm import Session
from datetime import datetime
from difflib import SequenceMatcher
import re

from app import models, schemas

from app.security import get_password_hash, verify_password


def get_products(db: Session) -> list[models.Product]:
    return db.query(models.Product).order_by(models.Product.id.desc()).all()


def create_product(db: Session, product: schemas.ProductCreate) -> models.Product:
    db_product = models.Product(
        name=product.name,
        description=product.description or '',
        category=product.category or '',
        price=product.price,
        cost=product.cost,
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


def get_customers(db: Session, business_id: int | None = None) -> list[models.Customer]:
    q = db.query(models.Customer)
    if business_id is not None:
        q = q.filter(models.Customer.business_id == business_id)
    return q.order_by(models.Customer.id.desc()).all()


def get_customer(db: Session, customer_id: int) -> models.Customer | None:
    return db.query(models.Customer).filter(models.Customer.id == customer_id).first()


def get_customer_by_phone(db: Session, phone: str) -> models.Customer | None:
    return db.query(models.Customer).filter(models.Customer.phone == phone).first()


def update_customer(db: Session, customer_id: int, customer: schemas.CustomerCreate) -> models.Customer | None:
    db_customer = get_customer(db, customer_id)
    if not db_customer:
        return None
    db_customer.first_name = customer.first_name or db_customer.first_name
    db_customer.last_name = customer.last_name or db_customer.last_name
    db_customer.phone = customer.phone or db_customer.phone
    db_customer.email = customer.email or db_customer.email
    db_customer.address = customer.address or db_customer.address
    db_customer.city = customer.city or db_customer.city
    db_customer.postal_code = customer.postal_code or db_customer.postal_code
    db.commit()
    db.refresh(db_customer)
    return db_customer


def patch_customer(db: Session, customer_id: int, customer: schemas.CustomerUpdate) -> models.Customer | None:
    db_customer = get_customer(db, customer_id)
    if not db_customer:
        return None
    for field in ("first_name", "last_name", "phone", "email", "address", "city", "postal_code"):
        value = getattr(customer, field)
        if value is not None:
            setattr(db_customer, field, value)
    db.commit()
    db.refresh(db_customer)
    return db_customer


def get_customer_history(db: Session, customer_id: int) -> dict:
    # return service requests and messages for the customer
    sreqs = db.query(models.ServiceRequest).filter(models.ServiceRequest.customer_id == customer_id).order_by(models.ServiceRequest.created_at.desc()).all()
    # messages via conversations
    convs = db.query(models.Conversation).filter(models.Conversation.customer_id == customer_id).all()
    msgs = []
    for c in convs:
        m = db.query(models.Message).filter(models.Message.conversation_id == c.id).order_by(models.Message.created_at.asc()).all()
        msgs.extend(m)
    return {"service_requests": sreqs, "messages": msgs}


def create_customer(db: Session, customer: schemas.CustomerCreate) -> models.Customer:
    db_customer = models.Customer(
        business_id=customer.business_id,
        first_name=customer.first_name or '',
        last_name=customer.last_name or '',
        phone=customer.phone,
        email=customer.email,
        address=customer.address,
        city=customer.city,
        postal_code=customer.postal_code,
        notes='')
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer


def get_user_by_email(db: Session, email: str) -> models.User | None:
    return db.query(models.User).filter(models.User.email == email).first()


def get_user(db: Session, user_id: int) -> models.User | None:
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_users(db: Session, business_id: int) -> list[models.User]:
    return (
        db.query(models.User)
        .filter(models.User.business_id == business_id)
        .order_by(models.User.first_name.asc(), models.User.last_name.asc(), models.User.id.asc())
        .all()
    )


def create_user(db: Session, user: schemas.UserCreate) -> models.User:
    hashed = get_password_hash(user.password)
    db_user = models.User(
        business_id=user.business_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        phone=None,
        password_hash=hashed,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def authenticate_user(db: Session, email: str, password: str) -> models.User | None:
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_service_requests(db: Session, business_id: int | None = None) -> list[models.ServiceRequest]:
    q = db.query(models.ServiceRequest)
    if business_id is not None:
        q = q.filter(models.ServiceRequest.business_id == business_id)
    return q.order_by(models.ServiceRequest.id.desc()).all()


def create_service_request(db: Session, req: schemas.ServiceRequestCreate) -> models.ServiceRequest:
    db_req = models.ServiceRequest(
        business_id=req.business_id,
        customer_id=req.customer_id,
        source=req.source,
        category=req.category,
        description=req.description,
        address=req.address,
        city=req.city,
        urgency=req.urgency,
    )
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    return db_req


def get_appointments(
    db: Session,
    business_id: int,
    start_datetime: datetime | None = None,
    end_datetime: datetime | None = None,
    assigned_user_id: int | None = None,
    include_completed: bool = True,
) -> list[models.Appointment]:
    q = db.query(models.Appointment).filter(models.Appointment.business_id == business_id)

    if start_datetime is not None:
        q = q.filter(models.Appointment.start_datetime >= start_datetime)

    if end_datetime is not None:
        q = q.filter(models.Appointment.start_datetime < end_datetime)

    if assigned_user_id is not None:
        q = q.filter(models.Appointment.assigned_user_id == assigned_user_id)

    if not include_completed:
        q = q.filter(models.Appointment.status != models.AppointmentStatus.COMPLETATO)

    return q.order_by(models.Appointment.start_datetime.asc()).all()


def get_appointment(db: Session, appointment_id: int) -> models.Appointment | None:
    return db.query(models.Appointment).filter(models.Appointment.id == appointment_id).first()


def get_appointment_by_service_request(
    db: Session,
    service_request_id: int,
) -> models.Appointment | None:
    return (
        db.query(models.Appointment)
        .filter(models.Appointment.service_request_id == service_request_id)
        .order_by(models.Appointment.id.desc())
        .first()
    )


def schedule_service_request(
    db: Session,
    service_request: models.ServiceRequest,
    appointment: schemas.AppointmentCreate,
) -> models.Appointment:
    if appointment.end_datetime is None:
        raise ValueError("end_datetime is required after schedule normalization")

    existing = get_appointment_by_service_request(db, service_request.id)

    assigned_user_id = (
        appointment.assigned_user_id
        if appointment.assigned_user_id is not None
        else service_request.assigned_user_id
    )

    if existing:
        existing.start_datetime = appointment.start_datetime
        existing.end_datetime = appointment.end_datetime
        existing.assigned_user_id = assigned_user_id
        existing.address = service_request.address
        existing.notes = appointment.notes
        existing.status = models.AppointmentStatus.CONFERMATO
        existing.customer_confirmed = True
        db_appointment = existing
    else:
        db_appointment = models.Appointment(
            business_id=service_request.business_id,
            service_request_id=service_request.id,
            customer_id=service_request.customer_id,
            assigned_user_id=assigned_user_id,
            start_datetime=appointment.start_datetime,
            end_datetime=appointment.end_datetime,
            address=service_request.address,
            status=models.AppointmentStatus.CONFERMATO,
            customer_confirmed=True,
            notes=appointment.notes,
        )
        db.add(db_appointment)

    service_request.status = models.RequestStatus.PROGRAMMATA
    if assigned_user_id is not None:
        service_request.assigned_user_id = assigned_user_id

    duration_minutes = max(
        1,
        round((appointment.end_datetime - appointment.start_datetime).total_seconds() / 60),
    )
    if service_request.estimated_duration_minutes is None:
        service_request.estimated_duration_minutes = duration_minutes

    db.commit()
    db.refresh(db_appointment)
    db.refresh(service_request)
    return db_appointment


def update_appointment(
    db: Session,
    appointment_id: int,
    payload: schemas.AppointmentUpdate,
) -> models.Appointment | None:
    appointment = get_appointment(db, appointment_id)
    if not appointment:
        return None

    if payload.start_datetime is not None:
        appointment.start_datetime = payload.start_datetime

    if payload.end_datetime is not None:
        appointment.end_datetime = payload.end_datetime
    elif payload.duration_minutes is not None and payload.start_datetime is not None:
        from datetime import timedelta
        appointment.end_datetime = payload.start_datetime + timedelta(minutes=payload.duration_minutes)
    elif payload.duration_minutes is not None:
        from datetime import timedelta
        appointment.end_datetime = appointment.start_datetime + timedelta(minutes=payload.duration_minutes)

    if payload.assigned_user_id is not None:
        appointment.assigned_user_id = payload.assigned_user_id

    if payload.customer_confirmed is not None:
        appointment.customer_confirmed = payload.customer_confirmed

    if payload.notes is not None:
        appointment.notes = payload.notes

    if payload.route_order is not None:
        appointment.route_order = payload.route_order

    if payload.travel_minutes is not None:
        appointment.travel_minutes = payload.travel_minutes

    if payload.status is not None:
        appointment.status = models.AppointmentStatus(payload.status)

    if appointment.end_datetime <= appointment.start_datetime:
        raise ValueError("end_datetime must be after start_datetime")

    db.commit()
    db.refresh(appointment)
    return appointment


def _normalize_problem_text(value: str | None) -> str:
    text_value = (value or "").lower().strip()
    return " ".join(re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text_value))


def estimate_service_request_duration(
    db: Session,
    service_request: models.ServiceRequest,
    default_minutes: int = 60,
    max_cases: int = 10,
) -> dict:
    target = _normalize_problem_text(
        f"{service_request.category or ''} {service_request.description or ''}"
    )

    rows = (
        db.query(models.ServiceRequest, models.Appointment)
        .join(
            models.Appointment,
            models.Appointment.service_request_id == models.ServiceRequest.id,
        )
        .filter(
            models.ServiceRequest.business_id == service_request.business_id,
            models.ServiceRequest.id != service_request.id,
            models.ServiceRequest.status == models.RequestStatus.COMPLETATA,
            models.Appointment.actual_duration_minutes.isnot(None),
            models.Appointment.actual_duration_minutes > 0,
        )
        .all()
    )

    scored: list[tuple[float, int]] = []
    for candidate, appointment in rows:
        candidate_text = _normalize_problem_text(
            f"{candidate.category or ''} {candidate.description or ''}"
        )
        if not candidate_text:
            continue

        score = SequenceMatcher(None, target, candidate_text).ratio() if target else 0.0
        if service_request.category and candidate.category:
            if service_request.category.strip().lower() == candidate.category.strip().lower():
                score = min(1.0, score + 0.15)

        if score >= 0.20:
            scored.append((score, int(appointment.actual_duration_minutes)))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[:max_cases]

    if not selected:
        return {
            "estimated_duration_minutes": default_minutes,
            "sample_count": 0,
            "confidence": "bassa",
        }

    weight_sum = sum(score for score, _ in selected)
    if weight_sum <= 0:
        estimate = default_minutes
    else:
        estimate = round(
            sum(score * minutes for score, minutes in selected) / weight_sum
        )

    # Calendar-friendly slot: round to nearest 15 minutes, minimum 30.
    estimate = max(30, min(480, int(round(estimate / 15.0) * 15)))

    avg_score = sum(score for score, _ in selected) / len(selected)
    if len(selected) >= 6 and avg_score >= 0.55:
        confidence = "alta"
    elif len(selected) >= 3 and avg_score >= 0.35:
        confidence = "media"
    else:
        confidence = "bassa"

    return {
        "estimated_duration_minutes": estimate,
        "sample_count": len(selected),
        "confidence": confidence,
    }


def create_request_attachment(db: Session, service_request_id: int, file_url: str, file_type: str | None = None, caption: str | None = None) -> models.RequestAttachment:
    att = models.RequestAttachment(
        service_request_id=service_request_id,
        file_url=file_url,
        file_type=file_type,
        caption=caption,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def get_request_attachments(db: Session, service_request_id: int) -> list[models.RequestAttachment]:
    return db.query(models.RequestAttachment).filter(models.RequestAttachment.service_request_id == service_request_id).order_by(models.RequestAttachment.id.desc()).all()


def get_service_request(db: Session, service_request_id: int) -> models.ServiceRequest | None:
    return db.query(models.ServiceRequest).filter(models.ServiceRequest.id == service_request_id).first()


def update_service_request(db: Session, service_request_id: int, **fields) -> models.ServiceRequest | None:
    sr = get_service_request(db, service_request_id)
    if not sr:
        return None
    for key, value in fields.items():
        if hasattr(sr, key) and value is not None:
            setattr(sr, key, value)
    db.commit()
    db.refresh(sr)
    return sr


def update_conversation(db: Session, conversation_id: int, **fields) -> models.Conversation | None:
    conv = db.query(models.Conversation).filter(models.Conversation.id == conversation_id).first()
    if not conv:
        return None
    for key, value in fields.items():
        if hasattr(conv, key) and value is not None:
            setattr(conv, key, value)
    db.commit()
    db.refresh(conv)
    return conv


def accept_service_request(
    db: Session,
    service_request_id: int,
    assigned_user_id: int | None = None,
) -> models.ServiceRequest | None:
    sr = get_service_request(db, service_request_id)
    if not sr:
        return None

    sr.status = models.RequestStatus.ACCETTATA
    if assigned_user_id is not None:
        sr.assigned_user_id = assigned_user_id

    db.commit()
    db.refresh(sr)
    return sr


def reject_service_request(db: Session, service_request_id: int) -> models.ServiceRequest | None:
    sr = get_service_request(db, service_request_id)
    if not sr:
        return None
    sr.status = models.RequestStatus.RIFIUTATA
    db.commit()
    db.refresh(sr)
    return sr


def assign_service_request(db: Session, service_request_id: int, assigned_user_id: int) -> models.ServiceRequest | None:
    sr = get_service_request(db, service_request_id)
    if not sr:
        return None
    sr.assigned_user_id = assigned_user_id
    sr.status = models.RequestStatus.PROGRAMMATA
    db.commit()
    db.refresh(sr)
    return sr


def start_service_request(
    db: Session,
    service_request_id: int,
) -> models.ServiceRequest | None:
    sr = get_service_request(db, service_request_id)
    if not sr:
        return None

    sr.status = models.RequestStatus.IN_CORSO

    appointment = get_appointment_by_service_request(db, service_request_id)
    if appointment:
        appointment.status = models.AppointmentStatus.IN_CORSO
        if appointment.actual_start is None:
            appointment.actual_start = datetime.utcnow()

    db.commit()
    db.refresh(sr)
    if appointment:
        db.refresh(appointment)
    return sr


def complete_service_request(
    db: Session,
    service_request_id: int,
) -> models.ServiceRequest | None:
    sr = get_service_request(db, service_request_id)
    if not sr:
        return None

    sr.status = models.RequestStatus.COMPLETATA

    appointment = get_appointment_by_service_request(db, service_request_id)
    if appointment:
        appointment.status = models.AppointmentStatus.COMPLETATO
        appointment.actual_end = datetime.utcnow()

        if appointment.actual_start is not None:
            duration_seconds = (
                appointment.actual_end - appointment.actual_start
            ).total_seconds()
            appointment.actual_duration_minutes = max(
                1,
                round(duration_seconds / 60),
            )

    db.commit()
    db.refresh(sr)
    if appointment:
        db.refresh(appointment)
    return sr


def get_conversation_by_customer_channel(db: Session, business_id: int, customer_id: int | None, channel: str) -> models.Conversation | None:
    q = db.query(models.Conversation).filter(models.Conversation.business_id == business_id, models.Conversation.channel == channel)
    if customer_id is not None:
        q = q.filter(models.Conversation.customer_id == customer_id)
    return q.order_by(models.Conversation.id.desc()).first()


def get_conversation(db: Session, conversation_id: int) -> models.Conversation | None:
    return db.query(models.Conversation).filter(models.Conversation.id == conversation_id).first()


def get_conversations(db: Session, business_id: int, channel: str | None = None) -> list[models.Conversation]:
    q = db.query(models.Conversation).filter(models.Conversation.business_id == business_id)
    if channel is not None:
        q = q.filter(models.Conversation.channel == channel)
    return q.order_by(models.Conversation.updated_at.desc()).all()


def get_messages(db: Session, conversation_id: int) -> list[models.Message]:
    return (
        db.query(models.Message)
        .filter(models.Message.conversation_id == conversation_id)
        .order_by(models.Message.created_at.asc())
        .all()
    )


def create_conversation(db: Session, business_id: int, customer_id: int | None, service_request_id: int | None, channel: str) -> models.Conversation:
    conv = models.Conversation(
        business_id=business_id,
        customer_id=customer_id,
        service_request_id=service_request_id,
        channel=channel,
        status="open",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def create_message(db: Session, conversation_id: int, sender_type: str, message_type: str, content: str | None = None, external_message_id: str | None = None) -> models.Message:
    msg = models.Message(
        conversation_id=conversation_id,
        sender_type=sender_type,
        message_type=message_type,
        content=content,
        external_message_id=external_message_id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg
