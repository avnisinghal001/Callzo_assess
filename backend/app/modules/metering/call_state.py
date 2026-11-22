"""Resolve what we know about one call from all of its events. Pure and order-independent:
any arrival order, and any number of duplicates, yields the same state."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from app.core.timeutil import utc_date
from app.modules.aggregates.buckets import Usage

# An event received this long after it happened is flagged late (the simulator sends ~35 days).
LATE_AFTER = timedelta(hours=72)

STARTED, ENDED, FAILED = "call.started", "call.ended", "call.failed"
IN_PROGRESS, COMPLETED, FAILED_STATUS = "in_progress", "completed", "failed"


@dataclass(frozen=True)
class CallEvent:
    id: UUID
    provider_event_id: str
    event_type: str
    occurred_at: datetime
    received_at: datetime
    duration_seconds: int
    cost_cents: int


@dataclass(frozen=True)
class CallState:
    status: str = IN_PROGRESS
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int = 0
    cost_cents: int = 0
    usage_date: date | None = None
    is_late: bool = False
    terminal_event_id: UUID | None = None


def resolve_call(events: Sequence[CallEvent]) -> CallState:
    """Terminal event wins: `ended` beats `failed`, then the later timestamp, then the larger
    provider_event_id (a deterministic final tie-break). Only `ended` carries duration and cost."""
    starts = [e.occurred_at for e in events if e.event_type == STARTED]
    terminals = [e for e in events if e.event_type in (ENDED, FAILED)]
    started_at = min(starts) if starts else None
    if not terminals:
        return CallState(started_at=started_at)

    winner = max(
        terminals, key=lambda e: (e.event_type == ENDED, e.occurred_at, e.provider_event_id)
    )
    completed = winner.event_type == ENDED
    return CallState(
        status=COMPLETED if completed else FAILED_STATUS,
        started_at=started_at,
        ended_at=winner.occurred_at,
        duration_seconds=winner.duration_seconds if completed else 0,
        cost_cents=winner.cost_cents if completed else 0,
        usage_date=utc_date(winner.occurred_at),
        is_late=winner.received_at - winner.occurred_at > LATE_AFTER,
        terminal_event_id=winner.id,
    )


def usage_of(state: CallState) -> Usage:
    """What this call currently contributes to usage. An unfinished call contributes nothing."""
    if state.status == IN_PROGRESS:
        return Usage()
    completed = state.status == COMPLETED
    return Usage(
        completed_calls=int(completed),
        failed_calls=int(not completed),
        duration_seconds=state.duration_seconds,
        cost_cents=state.cost_cents,
        late_calls=int(state.is_late),
        late_cost_cents=state.cost_cents if state.is_late else 0,
    )
