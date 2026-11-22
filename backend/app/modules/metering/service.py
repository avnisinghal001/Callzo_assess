"""Apply events to usage. The only place usage is written (besides reconcile).

Lock order (always): account (shared) -> call row -> aggregate rows (sorted).
A single order is what makes concurrent workers deadlock-free.
"""

import structlog

from app.core.db import Conn
from app.modules.accounts import repository as accounts
from app.modules.aggregates import repository as aggregates
from app.modules.aggregates.buckets import Period, deltas_for_change
from app.modules.inbox.models import InboxEvent
from app.modules.metering import repository as calls
from app.modules.metering.call_state import CallState, resolve_call, usage_of

log = structlog.get_logger()


class UnknownAccount(Exception):
    """The account may simply not be provisioned yet, so the event is retried, not dropped."""


def meter_call(
    conn: Conn, account_external_id: str, provider_call_id: str
) -> tuple[CallState, bool]:
    """Bring one call's contribution to usage up to date. Idempotent: calling it again, in any
    order, changes nothing the second time. Returns (state, changed).

    Instead of adding an event's numbers, recompute the call's state from all of its live events
    and apply only the difference from what the call already contributed. O(1): one call row,
    that call's few events, and 4 aggregate rows.
    """
    account = accounts.lock_shared(conn, account_external_id)
    if account is None:
        raise UnknownAccount(account_external_id)

    calls.ensure_call(conn, account.id, provider_call_id)
    previous = calls.lock_call(conn, account.id, provider_call_id)
    current = resolve_call(calls.load_events(conn, account_external_id, provider_call_id))
    if current == previous:
        return current, False

    deltas = deltas_for_change(
        previous.usage_date, usage_of(previous), current.usage_date, usage_of(current)
    )
    aggregates.apply_deltas(conn, account.id, deltas)
    months = [b.start for b in deltas if b.period is Period.MONTH]
    for row in aggregates.refresh_cap_flags(conn, account.id, months):
        log.warning(
            "cap_state_changed",
            account=account_external_id,
            month=row["period_start"].isoformat(),
            used_seconds=row["duration_seconds"],
            reached=row["cap_reached_at"] is not None,
            call=provider_call_id,
        )
    calls.save_call(conn, account.id, provider_call_id, current)
    return current, True


def apply_event(conn: Conn, event: InboxEvent) -> None:
    state, changed = meter_call(conn, event.account_external_id, event.provider_call_id)
    log.info(
        "event_metered",
        event_id=event.provider_event_id,
        account=event.account_external_id,
        call=event.provider_call_id,
        status=state.status,
        changed=changed,
    )
