from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.core.security import require_scope
from app.core.timeutil import utc_now
from app.core.types import AccountIdPath
from app.modules.aggregates.buckets import Period
from app.modules.usage import service
from app.modules.usage.schemas import CallPage, RangeOut, SeriesOut, SummaryOut

router = APIRouter(
    prefix="/v1/accounts/{account_id}/usage",
    tags=["usage"],
    dependencies=[Depends(require_scope("read"))],
)

FromDate = Annotated[date, Query(alias="from", description="First day, YYYY-MM-DD (UTC)")]
ToDate = Annotated[date, Query(alias="to", description="Last day, inclusive")]


@router.get("", response_model=SummaryOut)
def get_summary(request: Request, account_id: AccountIdPath, on: date | None = None) -> SummaryOut:
    """Today, this week, this month, lifetime and the cap state. `on` defaults to today (UTC)."""
    with request.app.state.pool.connection() as conn:
        return service.summary(conn, account_id, on or utc_now().date())


@router.get("/series", response_model=SeriesOut)
def get_series(
    request: Request,
    account_id: AccountIdPath,
    start: FromDate,
    end: ToDate,
    granularity: Literal["day", "week", "month"] = "day",
) -> SeriesOut:
    with request.app.state.pool.connection() as conn:
        return service.series(conn, account_id, Period(granularity), start, end)


@router.get("/range", response_model=RangeOut)
def get_range(
    request: Request, account_id: AccountIdPath, start: FromDate, end: ToDate
) -> RangeOut:
    """Exact total for any custom date range."""
    with request.app.state.pool.connection() as conn:
        return service.range_total(conn, account_id, start, end)


@router.get("/calls", response_model=CallPage)
def get_calls(
    request: Request,
    account_id: AccountIdPath,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CallPage:
    """Finished calls, newest first: the evidence behind the totals."""
    with request.app.state.pool.connection() as conn:
        return service.recent_calls(conn, account_id, cursor, limit)
