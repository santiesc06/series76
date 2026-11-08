"""Request and response models of the public API (design §4). They also generate /docs."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.agent.schemas import Status, View


class ConversationRequest(BaseModel):
    session_id: uuid.UUID | None = Field(
        None, description="Omit to start a new conversation; send it to continue one."
    )
    query: str = Field(min_length=1, max_length=2000, description="The user's question.")

    @field_validator("query")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


class SpecValue(BaseModel):
    value: float | None
    unit: str
    condition: str | None = None


class Spec(BaseModel):
    key: str
    label: str
    values: list[SpecValue]


class SpecGroup(BaseModel):
    key: str
    title: str
    specs: list[Spec]


class PowerSupply(BaseModel):
    label: str
    voltage: int
    phase: str | None
    current_type: str


class Product(BaseModel):
    part_number: str
    model_code: str
    enclosure: str
    power_supply: PowerSupply
    certifications: list[str]
    hazardous_markings: list[str]
    data_available: bool
    notes: list[str]
    highlight: list[str] = Field(description="Spec keys that matched the user's requirement.")
    match_note: str | None = Field(None, description="Why an alternative is not a full match.")
    spec_groups: list[SpecGroup]


class QuickReply(BaseModel):
    label: str
    message: str


class ConversationResponse(BaseModel):
    session_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    status: Status
    view: View
    products: list[Product]
    alternatives: list[Product] = Field(description="Closest models when nothing matches.")
    quick_replies: list[QuickReply]
    created_at: datetime


class SessionSummary(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class HistoryMessage(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    status: Status | None = None
    view: View | None = None
    products: list[Product] = []
    alternatives: list[Product] = []
    quick_replies: list[QuickReply] = []


class SessionMessages(BaseModel):
    session_id: uuid.UUID
    title: str
    messages: list[HistoryMessage]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class DebugInfo(BaseModel):
    """Developer-only view of one assistant answer."""

    model_config = {"extra": "allow"}

    message_id: uuid.UUID
    session_id: uuid.UUID
    model: str | None = None
    latency_ms: int | None = None
    tokens: dict[str, int] | None = None
    estimated_cost_usd: float | None = None
    steps: list[dict[str, Any]] = []
    number_check: dict[str, Any] | None = None


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, examples=["alice@series76.test"])
    password: str = Field(min_length=1, max_length=1024)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str


class LoginResponse(BaseModel):
    token: str = Field(description="Send it as `Authorization: Bearer <token>`.")
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserOut
