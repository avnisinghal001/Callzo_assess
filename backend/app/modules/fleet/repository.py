"""Shared, cross-server view of the running processes and of webhook traffic."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from app.core.db import Conn

HEARTBEAT = """
INSERT INTO service_instances (instance, role, metadata) VALUES (%s, %s, %s)
ON CONFLICT (instance) DO UPDATE SET last_seen_at = now(), metadata = EXCLUDED.metadata,
  deleted_at = NULL
"""

# Sorted input: every server locks the minute's rows in the same order, so flushes cannot deadlock.
ADD_OUTCOMES = """
INSERT INTO webhook_stats AS s (bucket_start, outcome, requests)
SELECT t.bucket_start, t.outcome, t.requests
FROM unnest(%s::timestamptz[], %s::text[], %s::bigint[]) AS t(bucket_start, outcome, requests)
ORDER BY t.bucket_start, t.outcome
ON CONFLICT (bucket_start, outcome) WHERE deleted_at IS NULL
DO UPDATE SET requests = s.requests + EXCLUDED.requests
"""

READ_OUTCOMES = """
SELECT bucket_start, outcome, requests FROM webhook_stats
WHERE bucket_start >= now() - make_interval(mins => %s) AND deleted_at IS NULL
ORDER BY bucket_start
"""

READ_INSTANCES = """
SELECT instance, role, created_at AS started_at, last_seen_at, metadata,
       extract(epoch FROM now() - last_seen_at)::float8 AS silent_seconds
FROM service_instances
WHERE deleted_at IS NULL AND last_seen_at > now() - interval '10 minutes'
ORDER BY last_seen_at DESC LIMIT 200
"""


def heartbeat(conn: Conn, instance: str, role: str, detail: Mapping[str, Any]) -> None:
    conn.execute(HEARTBEAT, (instance, role, Jsonb(dict(detail))))


def sign_off(conn: Conn, instance: str) -> None:
    conn.execute("UPDATE service_instances SET deleted_at = now() WHERE instance = %s", (instance,))


def add_outcomes(conn: Conn, counts: Mapping[tuple[datetime, str], int]) -> None:
    keys = sorted(counts)
    conn.execute(
        ADD_OUTCOMES, ([k[0] for k in keys], [k[1] for k in keys], [counts[k] for k in keys])
    )


def read_outcomes(conn: Conn, minutes: int) -> list[dict[str, Any]]:
    return conn.execute(READ_OUTCOMES, (minutes,)).fetchall()


def read_instances(conn: Conn) -> list[dict[str, Any]]:
    return conn.execute(READ_INSTANCES).fetchall()


def prune(conn: Conn, stats_days: int, instance_days: int) -> dict[str, int]:
    """Telemetry, not business data: old rows are really removed."""
    stats = conn.execute(
        "DELETE FROM webhook_stats WHERE bucket_start < now() - make_interval(days => %s)",
        (stats_days,),
    ).rowcount
    instances = conn.execute(
        "DELETE FROM service_instances WHERE last_seen_at < now() - make_interval(days => %s)",
        (instance_days,),
    ).rowcount
    return {"webhook_stats": stats, "service_instances": instances}
