from contextlib import suppress
from uuid import UUID

import structlog

from app.core.db import Conn
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.audit import service as audit
from app.modules.inbox import repository as repo
from app.modules.inbox.schemas import (
    EventDetail,
    EventOut,
    EventPage,
    EventStatusFilter,
    RequeuedCount,
)
from app.modules.metering.service import UnknownAccount, meter_call

log = structlog.get_logger()


def list_events(
    conn: Conn, *, status: EventStatusFilter, account: str | None, cursor: str | None, limit: int
) -> EventPage:
    if status == "all" and not account:
        raise ValidationFailed("status=all needs an account filter (it would scan everything)")
    voided = status == "voided"
    before = decode_cursor(cursor) if cursor else None
    rows = repo.list_events(
        conn,
        status=None if status in ("all", "voided") else status,
        voided=voided,
        account=account,
        before=before,
        limit=limit + 1,
    )
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_cursor(page[-1]["received_at"], page[-1]["id"]) if more else None
    return EventPage(items=[EventOut(**r) for r in page], next_cursor=next_cursor)


def get_event(conn: Conn, event_id: UUID) -> EventDetail:
    row = repo.get_event(conn, event_id)
    if row is None:
        raise NotFound("Unknown event")
    raw = bytes(row.pop("raw_body")).decode("utf-8", errors="replace")
    return EventDetail(**row, raw_body=raw)


def requeue(conn: Conn, event_id: UUID) -> EventOut:
    row = repo.requeue_one(conn, event_id)
    if row is None:
        raise Conflict("Only live pending or dead events can be requeued")
    audit.record(conn, "event.requeue", event_id)
    log.info("event_requeued", event_id=str(event_id))
    return EventOut(**row)


def requeue_dead(conn: Conn, account: str | None) -> RequeuedCount:
    count = repo.requeue_dead(conn, account)
    audit.record(conn, "event.requeue_dead", account or "all", requeued=count)
    log.info("dead_events_requeued", count=count, account=account)
    return RequeuedCount(requeued=count)


def void(conn: Conn, event_id: UUID, reason: str) -> EventDetail:
    """Exclude an event from usage (e.g. the provider sent bad data). If it had already been
    metered, the call is recomputed in the same transaction so totals are correct immediately."""
    row = repo.void(conn, event_id, reason)
    if row is None:
        raise Conflict("Event does not exist or is already voided")
    if row["status"] == "processed":
        with suppress(UnknownAccount):  # account gone: nothing left to correct
            meter_call(conn, row["account_external_id"], row["provider_call_id"])
    audit.record(conn, "event.void", event_id, reason=reason, account=row["account_external_id"])
    log.warning("event_voided", event_id=str(event_id), reason=reason)
    return get_event(conn, event_id)


def restore(conn: Conn, event_id: UUID) -> EventDetail:
    if repo.restore(conn, event_id) is None:
        raise Conflict("Event does not exist or is not voided")
    audit.record(conn, "event.restore", event_id)
    log.info("event_restored", event_id=str(event_id))
    return get_event(conn, event_id)
