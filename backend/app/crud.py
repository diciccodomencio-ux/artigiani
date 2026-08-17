from sqlalchemy.orm import Session

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


def get_appointments(db: Session, business_id: int) -> list[models.Appointment]:
    return (
        db.query(models.Appointment)
        .filter(models.Appointment.business_id == business_id)
        .order_by(models.Appointment.start_datetime.asc())
        .all()
    )


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


def accept_service_request(db: Session, service_request_id: int, assigned_user_id: int | None = None) -> models.ServiceRequest | None:
    sr = get_service_request(db, service_request_id)
    if not sr:
        return None
    sr.status = models.RequestStatus.ACCETTATA
    if assigned_user_id is not None:
        sr.assigned_user_id = assigned_user_id
    db.commit()
    db.refresh(sr)
    # create a draft appointment when accepted (default: next day, 1h)
    from datetime import datetime, timedelta
    from app import models as _models

    try:
        start = datetime.utcnow() + timedelta(days=1)
        end = start + timedelta(hours=1)
        ap = _models.Appointment(
            business_id=sr.business_id,
            service_request_id=sr.id,
            customer_id=sr.customer_id,
            assigned_user_id=sr.assigned_user_id,
            start_datetime=start,
            end_datetime=end,
            address=sr.address,
            status=_models.AppointmentStatus.PROPOSTO,
        )
        db.add(ap)
        db.commit()
        db.refresh(ap)
    except Exception:
        # do not fail accept if appointment creation fails
        pass

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


def complete_service_request(db: Session, service_request_id: int) -> models.ServiceRequest | None:
    sr = get_service_request(db, service_request_id)
    if not sr:
        return None
    sr.status = models.RequestStatus.COMPLETATA
    db.commit()
    db.refresh(sr)
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
