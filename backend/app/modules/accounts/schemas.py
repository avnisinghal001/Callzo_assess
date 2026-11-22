from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.types import ID_PATTERN, Metadata
from app.modules.usage.cap import CapStatus

MAX_CAP_MINUTES = 60 * 24 * 31  # a month of continuous calling: anything above is a typo


class AccountOut(BaseModel):
    id: UUID
    external_id: str
    monthly_cap_minutes: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    metadata: dict[str, Any]


class MonthBrief(BaseModel):
    used_seconds: int
    status: CapStatus
    new_calls_allowed: bool


class AccountListItem(AccountOut):
    month: MonthBrief


class AccountPage(BaseModel):
    items: list[AccountListItem]
    next_cursor: str | None


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(pattern=ID_PATTERN)
    monthly_cap_minutes: int = Field(ge=0, le=MAX_CAP_MINUTES)
    metadata: Metadata = Field(default_factory=dict)


class AccountPatch(BaseModel):
    """Only the fields present are changed. Metadata merges key by key; null removes a key."""

    model_config = ConfigDict(extra="forbid")

    monthly_cap_minutes: int | None = Field(default=None, ge=0, le=MAX_CAP_MINUTES)
    metadata: Metadata | None = None

    @model_validator(mode="after")
    def not_empty(self) -> "AccountPatch":
        if self.monthly_cap_minutes is None and self.metadata is None:
            raise ValueError("nothing to change")
        return self
