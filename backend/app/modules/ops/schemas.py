from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.types import ID_PATTERN
from app.modules.aggregates.buckets import Usage
from app.modules.ops.scenarios import Scenario
from app.modules.usage.schemas import CapOut

CallId = Annotated[str, Field(pattern=ID_PATTERN)]


class InboxStats(BaseModel):
    pending: int
    dead: int
    oldest_due_seconds: float


class MinuteStats(BaseModel):
    minute: datetime
    outcomes: dict[str, int]


class Instance(BaseModel):
    instance: str
    role: Literal["api", "worker"]
    started_at: datetime
    last_seen_at: datetime
    silent_seconds: float
    alive: bool
    metadata: dict[str, Any]


class Job(BaseModel):
    name: str
    interval_seconds: int
    next_run_at: datetime
    last_run_at: datetime | None
    last_result: dict[str, Any]


class Overview(BaseModel):
    """The whole fleet, from shared tables: the same answer whichever server replies."""

    server_time: datetime
    inbox: InboxStats
    traffic: list[MinuteStats]  # sparse: quiet minutes are omitted
    traffic_minutes: int
    instances: list[Instance]
    jobs: list[Job]
    pool_max_size: int
    sandbox_enabled: bool


class SandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Scenario
    account: str = Field(pattern=ID_PATTERN)
    count: int = Field(default=1, ge=1, le=100)


class SandboxResult(BaseModel):
    label: str  # event type, or what was wrong with the request
    event_id: str | None = None
    call_id: str | None = None
    outcome: Literal["accepted", "duplicate", "rejected"]
    status_code: int  # what a real sender would have received
    metric: str  # how it is counted


class SandboxResponse(BaseModel):
    scenario: Scenario
    account: str
    sent: int
    results: list[SandboxResult]
    call_ids: list[str]
    expected: Usage


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: str = Field(pattern=ID_PATTERN)
    call_ids: list[CallId] = Field(min_length=1, max_length=100)


class VerifyResponse(BaseModel):
    waiting_events: int  # not metered yet
    actual: Usage  # what these calls contribute to usage right now
    months: list[str]  # where that usage was booked, YYYY-MM
    call_uuids: list[UUID]
    cap: CapOut
