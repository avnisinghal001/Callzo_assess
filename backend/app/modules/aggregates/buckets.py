"""Additive usage math: pure functions, no I/O.

Usage is a commutative monoid under +, and a group once negation is allowed. That gives:
  * apply a change as a delta (new - old), so replays and corrections never double count;
  * any period total is the sum of its buckets, so a range is a few reads instead of a scan.

Buckets: DAY (UTC date), WEEK (ISO week, starts Monday), MONTH, LIFETIME. A WEEK bucket is
exactly the sum of the 7 DAY buckets it spans; a MONTH bucket the sum of its DAY buckets.
"""

from collections import defaultdict
from dataclasses import astuple, dataclass, fields
from datetime import date, timedelta
from enum import StrEnum
from typing import NamedTuple

from app.core.timeutil import month_end, month_start, next_month_start, week_start

LIFETIME_START = date(1970, 1, 1)


class Period(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    LIFETIME = "lifetime"


class Bucket(NamedTuple):
    period: Period
    start: date


@dataclass(frozen=True)
class Usage:
    """Everything a call can add to a bucket. Integers only: cents, seconds, counts."""

    completed_calls: int = 0
    failed_calls: int = 0
    duration_seconds: int = 0
    cost_cents: int = 0
    late_calls: int = 0
    late_cost_cents: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(*(a + b for a, b in zip(astuple(self), astuple(other), strict=True)))

    def __sub__(self, other: "Usage") -> "Usage":
        return Usage(*(a - b for a, b in zip(astuple(self), astuple(other), strict=True)))

    def is_zero(self) -> bool:
        return not any(astuple(self))


USAGE_COLUMNS = tuple(f.name for f in fields(Usage))


def buckets_for_day(day: date) -> tuple[Bucket, ...]:
    """The 4 buckets a day's usage belongs to. Constant size: this is the O(1) write."""
    return (
        Bucket(Period.DAY, day),
        Bucket(Period.WEEK, week_start(day)),
        Bucket(Period.MONTH, month_start(day)),
        Bucket(Period.LIFETIME, LIFETIME_START),
    )


def deltas_for_change(
    old_day: date | None, old: Usage, new_day: date | None, new: Usage
) -> dict[Bucket, Usage]:
    """Net change per bucket when a call's contribution moves from (old_day, old) to (new_day, new).

    Covers every case with one formula: first contribution (old is zero), replay (nothing
    changes), correction (failed -> ended), and a call moving between days or months.
    """
    deltas: dict[Bucket, Usage] = defaultdict(Usage)
    if old_day is not None:
        for bucket in buckets_for_day(old_day):
            deltas[bucket] = deltas[bucket] - old
    if new_day is not None:
        for bucket in buckets_for_day(new_day):
            deltas[bucket] = deltas[bucket] + new
    return {bucket: usage for bucket, usage in sorted(deltas.items()) if not usage.is_zero()}


def decompose_range(start: date, end: date) -> list[Bucket]:
    """Cover [start, end] inclusive exactly, with the fewest coarse buckets that are safe.

    Whole months in the middle; weeks then days at the two ragged edges (each edge is under a
    month, so at most ~6 days + 4 weeks + 6 days). Total reads ~ months + 32, never ~ days.
    Buckets never overlap, so summing them is exact.
    """
    if end < start:
        raise ValueError("end before start")
    first_month = start if start.day == 1 else next_month_start(start)
    months: list[date] = []
    cursor = first_month
    while month_end(cursor) <= end:
        months.append(cursor)
        cursor = next_month_start(cursor)
    if not months:
        return _weeks_and_days(start, end)
    return [
        *_weeks_and_days(start, first_month - timedelta(days=1)),
        *(Bucket(Period.MONTH, m) for m in months),
        *_weeks_and_days(cursor, end),
    ]


def _weeks_and_days(first: date, last: date) -> list[Bucket]:
    buckets: list[Bucket] = []
    day = first
    while day <= last:
        if day.weekday() == 0 and day + timedelta(days=6) <= last:
            buckets.append(Bucket(Period.WEEK, day))
            day += timedelta(days=7)
        else:
            buckets.append(Bucket(Period.DAY, day))
            day += timedelta(days=1)
    return buckets


def span(bucket: Bucket) -> tuple[date, date]:
    """First and last day a bucket covers (used by tests; LIFETIME has no finite span)."""
    match bucket.period:
        case Period.DAY:
            return bucket.start, bucket.start
        case Period.WEEK:
            return bucket.start, bucket.start + timedelta(days=6)
        case Period.MONTH:
            return bucket.start, month_end(bucket.start)
        case _:
            raise ValueError("lifetime has no finite span")
