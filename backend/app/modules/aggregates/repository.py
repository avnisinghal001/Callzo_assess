"""SQL for usage_aggregate. Every statement is keyed by account_id + period via the live
unique index (account_id, period_type, period_start) or a range on it: no table scans.
Soft-deleted rows are invisible to every statement here."""

import json
from datetime import date, datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.core.db import Conn
from app.modules.aggregates.buckets import USAGE_COLUMNS, Bucket, Period, Usage

_COLS = ", ".join(USAGE_COLUMNS)
_ARRAYS = ", ".join(f"%({c})s::bigint[]" for c in USAGE_COLUMNS)
_TARGETS = ", ".join(f"t.{c}" for c in USAGE_COLUMNS)
_ADD = ",\n  ".join(f"{c} = u.{c} + EXCLUDED.{c}" for c in USAGE_COLUMNS)
_SET = ",\n  ".join(f"{c} = EXCLUDED.{c}" for c in USAGE_COLUMNS)
_CONFLICT = "ON CONFLICT (account_id, period_type, period_start) WHERE deleted_at IS NULL"

# One round trip for all buckets. ORDER BY gives every worker the same row-lock order, so two
# workers touching overlapping buckets cannot deadlock. Keys are unique (merged upstream).
APPLY_DELTAS = f"""
INSERT INTO usage_aggregate AS u (account_id, period_type, period_start, {_COLS})
SELECT %(account_id)s, t.period_type, t.period_start, {_TARGETS}
FROM unnest(%(period_types)s::text[], %(period_starts)s::date[], {_ARRAYS})
  AS t(period_type, period_start, {_COLS})
ORDER BY t.period_type, t.period_start
{_CONFLICT} DO UPDATE SET
  {_ADD}
"""

# Reconcile: absolute values, only for buckets that drifted, with an audit note in metadata.
SET_ABSOLUTE = f"""
INSERT INTO usage_aggregate AS u (account_id, period_type, period_start, {_COLS}, metadata)
SELECT %(account_id)s, t.period_type, t.period_start, {_TARGETS}, t.metadata::jsonb
FROM unnest(%(period_types)s::text[], %(period_starts)s::date[], {_ARRAYS}, %(metadata)s::text[])
  AS t(period_type, period_start, {_COLS}, metadata)
ORDER BY t.period_type, t.period_start
{_CONFLICT} DO UPDATE SET
  {_SET},
  metadata = u.metadata || EXCLUDED.metadata
"""

# Set cap_reached_at on the first crossing, keep it after, clear it if usage falls back under.
# Only touches rows whose flag actually changes. Compared in seconds: no rounding.
REFRESH_CAP_FLAGS = """
UPDATE usage_aggregate u
SET cap_reached_at = CASE
      WHEN u.duration_seconds >= a.monthly_cap_minutes::bigint * 60 THEN now()
    END
FROM accounts a
WHERE a.id = u.account_id
  AND u.account_id = %s
  AND u.period_type = 'month'
  AND u.period_start = ANY(%s)
  AND u.deleted_at IS NULL
  AND (u.cap_reached_at IS NULL) = (u.duration_seconds >= a.monthly_cap_minutes::bigint * 60)
RETURNING u.period_start, u.duration_seconds, u.cap_reached_at
"""

READ_BUCKETS = f"""
SELECT u.period_type, u.period_start, {", ".join("u." + c for c in USAGE_COLUMNS)}
FROM usage_aggregate u
JOIN unnest(%s::text[], %s::date[]) AS k(period_type, period_start)
  ON u.period_type = k.period_type AND u.period_start = k.period_start
WHERE u.account_id = %s AND u.deleted_at IS NULL
"""

READ_SERIES = f"""
SELECT period_start, {_COLS}
FROM usage_aggregate
WHERE account_id = %s AND period_type = %s AND period_start BETWEEN %s AND %s
  AND deleted_at IS NULL
ORDER BY period_start
LIMIT %s
"""

READ_MONTH_MANY = f"""
SELECT account_id, {_COLS}, cap_reached_at
FROM usage_aggregate
WHERE account_id = ANY(%s) AND period_type = 'month' AND period_start = %s AND deleted_at IS NULL
"""

READ_ACCOUNT = f"""
SELECT period_type, period_start, cap_reached_at, {_COLS}
FROM usage_aggregate WHERE account_id = %s AND deleted_at IS NULL
"""

SOFT_DELETE_BUCKETS = """
UPDATE usage_aggregate u SET deleted_at = now(),
  metadata = u.metadata || %(note)s::jsonb
FROM unnest(%(period_types)s::text[], %(period_starts)s::date[]) AS k(period_type, period_start)
WHERE u.account_id = %(account_id)s AND u.period_type = k.period_type
  AND u.period_start = k.period_start AND u.deleted_at IS NULL
"""


def _usage(row: dict) -> Usage:
    return Usage(**{c: row[c] for c in USAGE_COLUMNS})


def _usage_arrays(account_id: UUID, items: dict[Bucket, Usage]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "account_id": account_id,
        "period_types": [b.period.value for b in items],
        "period_starts": [b.start for b in items],
    }
    for column in USAGE_COLUMNS:
        params[column] = [getattr(u, column) for u in items.values()]
    return params


def apply_deltas(conn: Conn, account_id: UUID, deltas: dict[Bucket, Usage]) -> None:
    if deltas:
        conn.execute(APPLY_DELTAS, _usage_arrays(account_id, deltas))


def set_absolute(
    conn: Conn, account_id: UUID, expected: dict[Bucket, Usage], audit: dict[Bucket, dict]
) -> None:
    if not expected:
        return
    params = _usage_arrays(account_id, expected)
    params["metadata"] = [json.dumps(audit[b]) for b in expected]
    conn.execute(SET_ABSOLUTE, params)


def soft_delete_buckets(conn: Conn, account_id: UUID, buckets: list[Bucket], note: dict) -> None:
    if buckets:
        conn.execute(
            SOFT_DELETE_BUCKETS,
            {
                "account_id": account_id,
                "period_types": [b.period.value for b in buckets],
                "period_starts": [b.start for b in buckets],
                "note": Jsonb(note),
            },
        )


def refresh_cap_flags(conn: Conn, account_id: UUID, months: list[date]) -> list[dict]:
    """Returns the month rows whose cap flag changed, so the caller can log the crossing."""
    if not months:
        return []
    return conn.execute(REFRESH_CAP_FLAGS, (account_id, months)).fetchall()


def read_buckets(conn: Conn, account_id: UUID, buckets: list[Bucket]) -> dict[Bucket, Usage]:
    if not buckets:
        return {}
    rows = conn.execute(
        READ_BUCKETS, ([b.period.value for b in buckets], [b.start for b in buckets], account_id)
    ).fetchall()
    return {Bucket(Period(r["period_type"]), r["period_start"]): _usage(r) for r in rows}


def read_month_many(
    conn: Conn, account_ids: list[UUID], month: date
) -> dict[UUID, tuple[Usage, datetime | None]]:
    if not account_ids:
        return {}
    rows = conn.execute(READ_MONTH_MANY, (account_ids, month)).fetchall()
    return {r["account_id"]: (_usage(r), r["cap_reached_at"]) for r in rows}


def read_month_cap_reached_at(conn: Conn, account_id: UUID, month: date) -> datetime | None:
    row = conn.execute(
        "SELECT cap_reached_at FROM usage_aggregate WHERE account_id = %s "
        "AND period_type = 'month' AND period_start = %s AND deleted_at IS NULL",
        (account_id, month),
    ).fetchone()
    return None if row is None else row["cap_reached_at"]


def read_series(
    conn: Conn, account_id: UUID, period: Period, first: date, last: date, limit: int
) -> list[tuple[date, Usage]]:
    rows = conn.execute(READ_SERIES, (account_id, period.value, first, last, limit)).fetchall()
    return [(r["period_start"], _usage(r)) for r in rows]


def read_all(conn: Conn, account_id: UUID) -> dict[Bucket, tuple[Usage, datetime | None]]:
    """Every live bucket of one account (reconcile only; walks the account's index prefix)."""
    rows = conn.execute(READ_ACCOUNT, (account_id,)).fetchall()
    return {
        Bucket(Period(r["period_type"]), r["period_start"]): (_usage(r), r["cap_reached_at"])
        for r in rows
    }
