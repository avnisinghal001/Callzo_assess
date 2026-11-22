from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.aggregates.buckets import Usage
from app.modules.usage.cap import CapStatus


class CapOut(BaseModel):
    monthly_cap_minutes: int
    used_seconds: int
    remaining_seconds: int
    overage_seconds: int
    status: CapStatus
    new_calls_allowed: bool
    reached_at: datetime | None


class SummaryOut(BaseModel):
    account_id: str
    on: date
    today: Usage
    this_week: Usage
    this_month: Usage
    lifetime: Usage
    cap: CapOut


class SeriesPoint(BaseModel):
    period_start: date
    usage: Usage


class SeriesOut(BaseModel):
    account_id: str
    granularity: Literal["day", "week", "month"]
    points: list[SeriesPoint]  # sparse: a period with no usage has no point


class RangeOut(BaseModel):
    account_id: str
    start: date
    end: date
    usage: Usage
    buckets_read: int  # how many pre-aggregated rows answered this


class CallOut(BaseModel):
    id: UUID
    provider_call_id: str
    status: Literal["in_progress", "completed", "failed"]
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int
    cost_cents: int
    is_late: bool
    terminal_event_id: UUID | None


class CallPage(BaseModel):
    items: list[CallOut]
    next_cursor: str | None
