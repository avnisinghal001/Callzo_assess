from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: UUID
    action: str
    target: str
    actor: str
    request_id: str | None
    created_at: datetime
    metadata: dict[str, Any]


class AuditPage(BaseModel):
    items: list[AuditEntry]
    next_cursor: str | None
