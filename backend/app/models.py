from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    Float,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship

from app.database import Base


class TradeType(PyEnum):
    ELETTRICISTA = "ELETTRICISTA"
    IDRAULICO = "IDRAULICO"
    CLIMATIZZAZIONE = "CLIMATIZZAZIONE"
    ALTRO = "ALTRO"


class Role(PyEnum):
    OWNER = "OWNER"
    TECHNICIAN = "TECHNICIAN"
    ADMIN = "ADMIN"


class RequestStatus(PyEnum):
    NUOVA = "NUOVA"
    IN_RACCOLTA_DATI = "IN_RACCOLTA_DATI"
    DA_VALUTARE = "DA_VALUTARE"
    ACCETTATA = "ACCETTATA"
    PROGRAMMATA = "PROGRAMMATA"
    IN_CORSO = "IN_CORSO"
    COMPLETATA = "COMPLETATA"
    RIFIUTATA = "RIFIUTATA"
    ANNULLATA = "ANNULLATA"
    IN_ATTESA_CLIENTE = "IN_ATTESA_CLIENTE"


class AppointmentStatus(PyEnum):
    PROPOSTO = "PROPOSTO"
    CONFERMATO = "CONFERMATO"
    IN_CORSO = "IN_CORSO"
    COMPLETATO = "COMPLETATO"
    ANNULLATO = "ANNULLATO"


class QuoteStatus(PyEnum):
    BOZZA = "BOZZA"
    DA_APPROVARE = "DA_APPROVARE"
    INVIATO = "INVIATO"
    ACCETTATO = "ACCETTATO"
    RIFIUTATO = "RIFIUTATO"
    SCADUTO = "SCADUTO"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(120), nullable=True)
    price = Column(Float, nullable=False)
    cost = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Business(Base):
    __tablename__ = "businesses"

    id = Column(Integer, primary_key=True, index=True)
    business_name = Column(String(200), nullable=False)
    trade_type = Column(SQLEnum(TradeType), nullable=False)
    phone = Column(String(50), nullable=True)
    email = Column(String(200), nullable=True)
    vat_number = Column(String(50), nullable=True)
    address = Column(String(300), nullable=True)
    service_area = Column(String(300), nullable=True)
    working_hours = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    first_name = Column(String(120), nullable=False)
    last_name = Column(String(120), nullable=True)
    email = Column(String(200), nullable=False, unique=True)
    phone = Column(String(50), nullable=True)
    password_hash = Column(String(300), nullable=False)
    role = Column(SQLEnum(Role), default=Role.OWNER)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    business = relationship("Business")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    first_name = Column(String(120), nullable=True)
    last_name = Column(String(120), nullable=True)
    phone = Column(String(50), nullable=True, index=True)
    email = Column(String(200), nullable=True)
    address = Column(String(300), nullable=True)
    city = Column(String(120), nullable=True)
    postal_code = Column(String(20), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = relationship("Business")


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    source = Column(String(50), nullable=True)
    category = Column(String(120), nullable=True)
    description = Column(Text, nullable=True)
    address = Column(String(300), nullable=True)
    city = Column(String(120), nullable=True)
    urgency = Column(String(50), nullable=True)
    status = Column(SQLEnum(RequestStatus), default=RequestStatus.NUOVA)
    ai_summary = Column(Text, nullable=True)
    ai_possible_cause = Column(Text, nullable=True)
    estimated_duration_minutes = Column(Integer, nullable=True)
    estimated_price_min = Column(Float, nullable=True)
    estimated_price_max = Column(Float, nullable=True)
    preferred_date = Column(DateTime, nullable=True)
    preferred_time = Column(String(50), nullable=True)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = relationship("Business")
    customer = relationship("Customer")


class RequestAttachment(Base):
    __tablename__ = "request_attachments"

    id = Column(Integer, primary_key=True, index=True)
    service_request_id = Column(Integer, ForeignKey("service_requests.id"), nullable=False)
    file_url = Column(String(1000), nullable=False)
    file_type = Column(String(50), nullable=True)
    caption = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    service_request_id = Column(Integer, ForeignKey("service_requests.id"), nullable=True)
    channel = Column(String(50), nullable=True)
    status = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    sender_type = Column(String(50), nullable=False)
    message_type = Column(String(50), nullable=False)
    content = Column(Text, nullable=True)
    external_message_id = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    service_request_id = Column(Integer, ForeignKey("service_requests.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    start_datetime = Column(DateTime, nullable=False)
    end_datetime = Column(DateTime, nullable=False)
    address = Column(String(300), nullable=True)
    status = Column(SQLEnum(AppointmentStatus), default=AppointmentStatus.PROPOSTO)
    customer_confirmed = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Quote(Base):
    __tablename__ = "quotes"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    service_request_id = Column(Integer, ForeignKey("service_requests.id"), nullable=True)
    quote_number = Column(String(100), nullable=True)
    status = Column(SQLEnum(QuoteStatus), default=QuoteStatus.BOZZA)
    subtotal = Column(Float, nullable=True)
    tax_amount = Column(Float, nullable=True)
    total = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class QuoteItem(Base):
    __tablename__ = "quote_items"

    id = Column(Integer, primary_key=True, index=True)
    quote_id = Column(Integer, ForeignKey("quotes.id"), nullable=False)
    item_type = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    quantity = Column(Float, nullable=True)
    unit_price = Column(Float, nullable=True)
    total_price = Column(Float, nullable=True)


class AIEvent(Base):
    __tablename__ = "ai_events"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    service_request_id = Column(Integer, ForeignKey("service_requests.id"), nullable=True)
    event_type = Column(String(100), nullable=True)
    input_data = Column(Text, nullable=True)
    output_data = Column(Text, nullable=True)
    model_name = Column(String(200), nullable=True)
    was_approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

