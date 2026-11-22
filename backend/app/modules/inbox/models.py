from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class NewEvent:
    provider_event_id: str
    event_type: str
    account_external_id: str
    provider_call_id: str
    occurred_at: datetime
    duration_seconds: int
    cost_cents: int
    destination_country: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InboxEvent:
    id: UUID
    provider_event_id: str
    event_type: str
    account_external_id: str
    provider_call_id: str
    attempts: int
