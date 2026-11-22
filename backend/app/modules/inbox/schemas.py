from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EventStatusFilter = Literal["pending", "processed", "dead", "voided", "all"]


class EventOut(BaseModel):
    id: UUID
    provider_event_id: str
    event_type: str
    account_external_id: str
    provider_call_id: str
    occurred_at: datetime
    received_at: datetime
    duration_seconds: int
    cost_cents: int
    destination_country: str
    status: Literal["pending", "processed", "dead"]
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None  # set = voided
    metadata: dict[str, Any]


class EventDetail(EventOut):
    raw_body: str  # exactly what was signed, decoded for display


class EventPage(BaseModel):
    items: list[EventOut]
    next_cursor: str | None


class VoidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class RequeuedCount(BaseModel):
    requeued: int
