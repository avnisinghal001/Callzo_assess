"""The durable inbox: store once, claim safely, record the outcome.

Postgres is the queue. Claiming is its own short transaction that bumps `attempts` and pushes
`next_attempt_at` out by a lease, using `FOR UPDATE SKIP LOCKED` so workers take different events
without waiting. Two consequences:
  * an event that crashes the worker process on every attempt still burns attempts and goes
    dead after max_attempts (a poison event cannot loop forever);
  * if a worker dies mid-event, the event simply becomes due again when the lease expires.
Processing is idempotent, so a repeat execution is harmless.

There is deliberately no NOTIFY here. Postgres takes a database-wide lock to commit a notifying
transaction, so commits serialize: measured 1,400-1,900 vs 4,000 inserts/s. Workers poll the tiny
partial index instead, which also keeps them compatible with PgBouncer transaction pooling.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.core.db import Conn
from app.modules.inbox.models import InboxEvent, NewEvent

INSERT_EVENT = """
INSERT INTO call_events (provider_event_id, account_external_id, provider_call_id, event_type,
                         occurred_at, duration_seconds, cost_cents, destination_country,
                         raw_body, metadata)
VALUES (%(provider_event_id)s, %(account_external_id)s, %(provider_call_id)s, %(event_type)s,
        %(occurred_at)s, %(duration_seconds)s, %(cost_cents)s, %(destination_country)s,
        %(raw_body)s, %(metadata)s)
ON CONFLICT (provider_event_id) DO NOTHING
RETURNING id
"""

# Deliberately includes voided rows: a redelivered voided event is still a duplicate.
SELECT_EXISTING = """
SELECT account_external_id, provider_call_id, event_type, occurred_at, duration_seconds, cost_cents,
       destination_country
FROM call_events WHERE provider_event_id = %s
"""

CLAIM_DUE = """
UPDATE call_events
SET attempts = attempts + 1,
    next_attempt_at = now() + make_interval(secs => %(lease)s)
WHERE id = (
  SELECT id FROM call_events
  WHERE status = 'pending' AND deleted_at IS NULL AND next_attempt_at <= now()
  ORDER BY next_attempt_at
  LIMIT 1
  FOR UPDATE SKIP LOCKED
)
RETURNING id, provider_event_id, event_type, account_external_id, provider_call_id, attempts
"""

MARK_FAILED = """
UPDATE call_events
SET last_error = %(error)s,
    status = CASE WHEN attempts >= %(max_attempts)s THEN 'dead' ELSE 'pending' END,
    next_attempt_at = now() + make_interval(secs => %(delay)s)
WHERE id = %(id)s
RETURNING status
"""

EVENT_COLUMNS = """id, provider_event_id, event_type, account_external_id, provider_call_id,
  occurred_at, received_at, duration_seconds, cost_cents, destination_country, status, attempts,
  next_attempt_at, last_error, processed_at, created_at, updated_at, deleted_at, metadata"""


def insert_event(conn: Conn, event: NewEvent, raw_body: bytes) -> bool:
    """True if stored now; False if this provider_event_id already exists."""
    params = {**event.__dict__, "raw_body": raw_body, "metadata": Jsonb(event.metadata)}
    return conn.execute(INSERT_EVENT, params).fetchone() is not None


def is_same_event(conn: Conn, event: NewEvent) -> bool:
    """Same id arriving again: a harmless resend, or a conflicting payload?"""
    row = conn.execute(SELECT_EXISTING, (event.provider_event_id,)).fetchone()
    return row is not None and row == {
        "account_external_id": event.account_external_id,
        "provider_call_id": event.provider_call_id,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "duration_seconds": event.duration_seconds,
        "cost_cents": event.cost_cents,
        "destination_country": event.destination_country,
    }


def claim_due(conn: Conn, lease_seconds: float) -> InboxEvent | None:
    row = conn.execute(CLAIM_DUE, {"lease": lease_seconds}).fetchone()
    return None if row is None else InboxEvent(**row)


def mark_processed(conn: Conn, event_id: UUID) -> None:
    conn.execute(
        "UPDATE call_events SET status = 'processed', processed_at = now(), last_error = NULL "
        "WHERE id = %s",
        (event_id,),
    )


def mark_failed(
    conn: Conn, event_id: UUID, error: str, delay_seconds: float, max_attempts: int
) -> str:
    row = conn.execute(
        MARK_FAILED,
        {
            "id": event_id,
            "error": error[:500],
            "delay": delay_seconds,
            "max_attempts": max_attempts,
        },
    ).fetchone()
    return row["status"]


def mark_dead(conn: Conn, event_id: UUID, error: str) -> None:
    conn.execute(
        "UPDATE call_events SET status = 'dead', last_error = %s WHERE id = %s",
        (error[:500], event_id),
    )


# ---- operator queries (console) ---------------------------------------------------------


def list_events(
    conn: Conn,
    *,
    status: str | None,
    voided: bool,
    account: str | None,
    before: tuple[datetime, UUID] | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Newest first, keyset-paginated. Each filter combination has an index:
    status -> call_events_by_status, account -> call_events_by_account,
    voided -> call_events_voided."""
    where = ["deleted_at IS NOT NULL" if voided else "deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": limit}
    if status:
        where.append("status = %(status)s")
        params["status"] = status
    if account:
        where.append("account_external_id = %(account)s")
        params["account"] = account
    if before:
        where.append("(received_at, id) < (%(before_at)s, %(before_id)s)")
        params["before_at"], params["before_id"] = before
    sql = (
        f"SELECT {EVENT_COLUMNS} FROM call_events WHERE {' AND '.join(where)} "
        "ORDER BY received_at DESC, id DESC LIMIT %(limit)s"
    )
    return conn.execute(sql, params).fetchall()


def get_event(conn: Conn, event_id: UUID) -> dict[str, Any] | None:
    return conn.execute(
        f"SELECT {EVENT_COLUMNS}, raw_body FROM call_events WHERE id = %s", (event_id,)
    ).fetchone()


def requeue_one(conn: Conn, event_id: UUID) -> dict[str, Any] | None:
    """pending/dead (live) -> pending and due now. None if the event is not in such a state."""
    return conn.execute(
        f"""UPDATE call_events SET status = 'pending', attempts = 0, next_attempt_at = now(),
               last_error = NULL
            WHERE id = %s AND deleted_at IS NULL AND status IN ('pending', 'dead')
            RETURNING {EVENT_COLUMNS}""",
        (event_id,),
    ).fetchone()


def requeue_dead(conn: Conn, account: str | None = None) -> int:
    where = "status = 'dead' AND deleted_at IS NULL"
    params: tuple = ()
    if account:
        where += " AND account_external_id = %s"
        params = (account,)
    cur = conn.execute(
        f"UPDATE call_events SET status = 'pending', attempts = 0, next_attempt_at = now(), "
        f"last_error = NULL WHERE {where}",
        params,
    )
    return cur.rowcount


def void(conn: Conn, event_id: UUID, reason: str) -> dict[str, Any] | None:
    return conn.execute(
        """UPDATE call_events SET deleted_at = now(),
             metadata = metadata || jsonb_build_object(
               'void', jsonb_build_object('reason', %s::text, 'at', now()))
           WHERE id = %s AND deleted_at IS NULL
           RETURNING id, status, account_external_id, provider_call_id""",
        (reason, event_id),
    ).fetchone()


def restore(conn: Conn, event_id: UUID) -> dict[str, Any] | None:
    """Un-void. The event goes back to pending so a worker applies it again."""
    return conn.execute(
        """UPDATE call_events SET deleted_at = NULL, status = 'pending', attempts = 0,
             next_attempt_at = now(), processed_at = NULL, last_error = NULL,
             metadata = (metadata - 'void') || jsonb_build_object('restored_at', now())
           WHERE id = %s AND deleted_at IS NOT NULL
           RETURNING id, account_external_id, provider_call_id""",
        (event_id,),
    ).fetchone()
