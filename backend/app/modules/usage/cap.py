"""Soft monthly cap. Pure integer math in seconds: no floats, no rounding at the boundary.

Usage is always recorded (the calls already happened). Once the month reaches the cap, the
caller is told new calls are not allowed. This service cannot stop a call in progress:
it has no call-control interface, so overshoot is bounded by calls already running.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

CapStatus = Literal["ok", "warning", "reached", "exceeded"]
WARNING_PERCENT = 80


@dataclass(frozen=True)
class CapView:
    monthly_cap_minutes: int
    used_seconds: int
    remaining_seconds: int
    overage_seconds: int
    status: CapStatus
    new_calls_allowed: bool
    reached_at: datetime | None


def cap_view(used_seconds: int, cap_minutes: int, reached_at: datetime | None) -> CapView:
    cap_seconds = cap_minutes * 60
    if used_seconds > cap_seconds:
        status: CapStatus = "exceeded"
    elif used_seconds == cap_seconds:
        status = "reached"  # exactly at the cap counts as reached: new calls stop here
    elif used_seconds * 100 >= cap_seconds * WARNING_PERCENT:
        status = "warning"
    else:
        status = "ok"
    return CapView(
        monthly_cap_minutes=cap_minutes,
        used_seconds=used_seconds,
        remaining_seconds=max(cap_seconds - used_seconds, 0),
        overage_seconds=max(used_seconds - cap_seconds, 0),
        status=status,
        new_calls_allowed=used_seconds < cap_seconds,
        reached_at=reached_at,
    )
