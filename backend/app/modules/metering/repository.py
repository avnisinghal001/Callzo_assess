from datetime import datetime
from typing import Any
from uuid import UUID

from app.core.db import Conn
from app.modules.metering.call_state import CallEvent, CallState

# Creating the row first means there is always something to lock, so two workers handling
# different events of the same call serialize here instead of both applying the same delta.
ENSURE_CALL = """
INSERT INTO calls (account_id, provider_call_id) VALUES (%s, %s)
ON CONFLICT (account_id, provider_call_id) WHERE deleted_at IS NULL DO NOTHING
"""

STATE_COLUMNS = """status, started_at, ended_at, duration_seconds, cost_cents, usage_date,
  is_late, terminal_event_id"""

LOCK_CALL = f"""
SELECT {STATE_COLUMNS} FROM calls
WHERE account_id = %s AND provider_call_id = %s AND deleted_at IS NULL FOR UPDATE
"""

# Voided (soft-deleted) events do not exist as far as metering is concerned.
LOAD_EVENTS = """
SELECT id, provider_event_id, event_type, occurred_at, received_at, duration_seconds, cost_cents
FROM call_events
WHERE account_external_id = %s AND provider_call_id = %s AND deleted_at IS NULL
"""

SAVE_CALL = """
UPDATE calls
SET status = %(status)s, started_at = %(started_at)s, ended_at = %(ended_at)s,
    duration_seconds = %(duration_seconds)s, cost_cents = %(cost_cents)s,
    usage_date = %(usage_date)s, is_late = %(is_late)s, terminal_event_id = %(terminal_event_id)s
WHERE account_id = %(account_id)s AND provider_call_id = %(provider_call_id)s
  AND deleted_at IS NULL
"""

LIST_CALLS = """
SELECT id, provider_call_id, status, started_at, ended_at, duration_seconds, cost_cents,
       is_late, terminal_event_id
FROM calls
WHERE account_id = %(account_id)s AND deleted_at IS NULL AND ended_at IS NOT NULL
  {cursor}
ORDER BY ended_at DESC, id DESC
LIMIT %(limit)s
"""


READ_CALLS = f"""
SELECT c.id, {", ".join("c." + c.strip() for c in STATE_COLUMNS.split(","))}
FROM calls c JOIN accounts a ON a.id = c.account_id
WHERE a.external_id = %s AND c.provider_call_id = ANY(%s) AND c.deleted_at IS NULL
"""

COUNT_WAITING = """
SELECT count(*) AS n FROM call_events
WHERE account_external_id = %s AND provider_call_id = ANY(%s) AND deleted_at IS NULL
  AND status = 'pending'
"""


def read_calls(
    conn: Conn, account_external_id: str, provider_call_ids: list[str]
) -> list[tuple[UUID, CallState]]:
    rows = conn.execute(READ_CALLS, (account_external_id, provider_call_ids)).fetchall()
    return [(r.pop("id"), CallState(**r)) for r in rows]


def count_waiting_events(conn: Conn, account_external_id: str, provider_call_ids: list[str]) -> int:
    return conn.execute(COUNT_WAITING, (account_external_id, provider_call_ids)).fetchone()["n"]


def ensure_call(conn: Conn, account_id: UUID, provider_call_id: str) -> None:
    conn.execute(ENSURE_CALL, (account_id, provider_call_id))


def lock_call(conn: Conn, account_id: UUID, provider_call_id: str) -> CallState:
    return CallState(**conn.execute(LOCK_CALL, (account_id, provider_call_id)).fetchone())


def load_events(conn: Conn, account_external_id: str, provider_call_id: str) -> list[CallEvent]:
    rows = conn.execute(LOAD_EVENTS, (account_external_id, provider_call_id)).fetchall()
    return [CallEvent(**r) for r in rows]


def save_call(conn: Conn, account_id: UUID, provider_call_id: str, state: CallState) -> None:
    conn.execute(
        SAVE_CALL,
        {**state.__dict__, "account_id": account_id, "provider_call_id": provider_call_id},
    )


def list_calls(
    conn: Conn, account_id: UUID, before: tuple[datetime, UUID] | None, limit: int
) -> list[dict[str, Any]]:
    """Finished calls, newest first, keyset-paginated on calls_recent."""
    params: dict[str, Any] = {"account_id": account_id, "limit": limit}
    cursor = ""
    if before:
        cursor = "AND (ended_at, id) < (%(before_at)s, %(before_id)s)"
        params["before_at"], params["before_id"] = before
    return conn.execute(LIST_CALLS.format(cursor=cursor), params).fetchall()
