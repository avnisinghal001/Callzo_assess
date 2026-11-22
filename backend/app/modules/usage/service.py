from datetime import date

from app.core.db import Conn
from app.core.errors import NotFound, ValidationFailed
from app.core.pagination import decode_cursor, encode_cursor
from app.core.timeutil import month_start, week_start
from app.modules.accounts import repository as accounts
from app.modules.accounts.repository import Account
from app.modules.aggregates import repository as aggregates
from app.modules.aggregates.buckets import (
    LIFETIME_START,
    Bucket,
    Period,
    Usage,
    decompose_range,
)
from app.modules.metering import repository as calls
from app.modules.usage.cap import cap_view
from app.modules.usage.schemas import (
    CallOut,
    CallPage,
    CapOut,
    RangeOut,
    SeriesOut,
    SeriesPoint,
    SummaryOut,
)

# Longest span each granularity may return / sum, keeping every response bounded.
MAX_SERIES_DAYS = {Period.DAY: 366, Period.WEEK: 1096, Period.MONTH: 3660}
MAX_RANGE_DAYS = 3660
SERIES_ROW_LIMIT = 1000


def _require_account(conn: Conn, external_id: str) -> Account:
    account = accounts.get(conn, external_id)
    if account is None:
        raise NotFound("Unknown account")
    return account


def _check_span(first: date, last: date, max_days: int) -> None:
    if last < first:
        raise ValidationFailed("`to` is before `from`")
    if (last - first).days + 1 > max_days:
        raise ValidationFailed(f"Range too long: at most {max_days} days")


def summary(conn: Conn, external_id: str, on: date) -> SummaryOut:
    """Four index reads, however much history the account has."""
    account = _require_account(conn, external_id)
    wanted = {
        "today": Bucket(Period.DAY, on),
        "this_week": Bucket(Period.WEEK, week_start(on)),
        "this_month": Bucket(Period.MONTH, month_start(on)),
        "lifetime": Bucket(Period.LIFETIME, LIFETIME_START),
    }
    found = aggregates.read_buckets(conn, account.id, list(wanted.values()))
    totals = {name: found.get(bucket, Usage()) for name, bucket in wanted.items()}
    reached_at = aggregates.read_month_cap_reached_at(conn, account.id, month_start(on))
    cap = cap_view(totals["this_month"].duration_seconds, account.monthly_cap_minutes, reached_at)
    return SummaryOut(account_id=external_id, on=on, cap=CapOut(**cap.__dict__), **totals)


def series(conn: Conn, external_id: str, granularity: Period, first: date, last: date) -> SeriesOut:
    account = _require_account(conn, external_id)
    _check_span(first, last, MAX_SERIES_DAYS[granularity])
    # A week/month bucket belongs to the range if it starts inside it.
    rows = aggregates.read_series(conn, account.id, granularity, first, last, SERIES_ROW_LIMIT)
    return SeriesOut(
        account_id=external_id,
        granularity=granularity.value,  # type: ignore[arg-type]
        points=[SeriesPoint(period_start=start, usage=usage) for start, usage in rows],
    )


def range_total(conn: Conn, external_id: str, first: date, last: date) -> RangeOut:
    """Hybrid for custom ranges: whole months, weeks and days chosen so they tile the range
    exactly. Reads ~months + 32 rows instead of one row per day."""
    account = _require_account(conn, external_id)
    _check_span(first, last, MAX_RANGE_DAYS)
    buckets = decompose_range(first, last)
    found = aggregates.read_buckets(conn, account.id, buckets)
    total = sum(found.values(), Usage())
    return RangeOut(
        account_id=external_id, start=first, end=last, usage=total, buckets_read=len(buckets)
    )


def recent_calls(conn: Conn, external_id: str, cursor: str | None, limit: int) -> CallPage:
    """The evidence behind a total: finished calls, newest first."""
    account = _require_account(conn, external_id)
    before = decode_cursor(cursor) if cursor else None
    rows = calls.list_calls(conn, account.id, before, limit + 1)
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_cursor(page[-1]["ended_at"], page[-1]["id"]) if more else None
    return CallPage(items=[CallOut(**r) for r in page], next_cursor=next_cursor)
