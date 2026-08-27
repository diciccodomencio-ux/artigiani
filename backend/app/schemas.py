from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProductCreate(BaseModel):
    name: str
    description: str | None = ''
    category: str | None = ''
    price: float
    cost: float


# --- Auth / User schemas


class UserCreate(BaseModel):
    business_id: int
    first_name: str
    last_name: str | None = None
    email: str
    password: str


class UserRead(ORMModel):
    id: int
    business_id: int
    first_name: str
    last_name: str | None = None
    email: str
    role: str


class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str | None = None


class TokenData(BaseModel):
    email: str | None = None


class RequestAttachmentRead(ORMModel):
    id: int
    service_request_id: int
    file_url: str
    file_type: str | None = None
    caption: str | None = None
    created_at: datetime | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ProductRead(ORMModel):
    id: int
    name: str
    description: str | None = ''
    category: str | None = ''
    price: float
    cost: float


class CustomerCreate(BaseModel):
    business_id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None


class CustomerRead(ORMModel):
    id: int
    business_id: int
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CustomerSummary(ORMModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None


class CustomerUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None


class ServiceRequestCreate(BaseModel):
    business_id: int | None = None
    customer_id: int | None = None
    source: str | None = None
    category: str | None = None
    description: str | None = None
    address: str | None = None
    city: str | None = None
    urgency: str | None = None


class ServiceRequestRead(ORMModel):
    id: int
    business_id: int
    customer_id: int | None = None
    source: str | None = None
    category: str | None = None
    description: str | None = None
    address: str | None = None
    city: str | None = None
    urgency: str | None = None
    status: str | None = None
    ai_summary: str | None = None
    ai_possible_cause: str | None = None
    estimated_duration_minutes: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    estimated_price_min: float | None = None
    estimated_price_max: float | None = None
    preferred_date: datetime | None = None
    preferred_time: str | None = None
    assigned_user_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    customer: CustomerSummary | None = None


class AppointmentCreate(BaseModel):
    start_datetime: datetime
    end_datetime: datetime | None = None
    duration_minutes: int | None = None
    assigned_user_id: int | None = None
    notes: str | None = None


class AppointmentUpdate(BaseModel):
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    duration_minutes: int | None = None
    assigned_user_id: int | None = None
    status: str | None = None
    customer_confirmed: bool | None = None
    notes: str | None = None
    route_order: int | None = None
    travel_minutes: int | None = None


class AppointmentRead(ORMModel):
    id: int
    business_id: int
    service_request_id: int | None = None
    customer_id: int | None = None
    assigned_user_id: int | None = None
    start_datetime: datetime
    end_datetime: datetime
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    actual_duration_minutes: int | None = None
    route_order: int | None = None
    travel_minutes: int | None = None
    proposal_expires_at: datetime | None = None
    proposal_round: int | None = None
    address: str | None = None
    status: str | None = None
    customer_confirmed: bool
    notes: str | None = None


class DurationEstimateRead(BaseModel):
    estimated_duration_minutes: int
    sample_count: int
    confidence: str


class ServiceRequestLocationUpdate(BaseModel):
    latitude: float
    longitude: float


class DashboardSummary(BaseModel):
    new_requests: int
    accepted_requests: int
    completed_requests: int
    customer_count: int
    total_requests: int


class MessageRead(ORMModel):
    id: int
    conversation_id: int
    sender_type: str
    message_type: str
    content: str | None = None
    created_at: datetime | None = None


class ConversationRead(ORMModel):
    id: int
    business_id: int
    customer_id: int | None = None
    service_request_id: int | None = None
    channel: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]


class OutboundMessageCreate(BaseModel):
    body: str


class CustomerHistory(BaseModel):
    service_requests: list[ServiceRequestRead]
    messages: list[MessageRead]
