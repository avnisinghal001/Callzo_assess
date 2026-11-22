"""No hot query may fall back to a sequential scan.

Seqscans are disabled for the check, so a seqscan can only appear in the plan when no index
could serve the query at all (a missing or unusable index), regardless of how tiny the test
tables are."""

import uuid
from datetime import date, datetime

import pytest

from app.modules.aggregates import repository as aggregates
from app.modules.audit import service as audit
from app.modules.fleet import repository as fleet
from app.modules.inbox import repository as inbox
from app.modules.jobs import service as jobs
from app.modules.metering import repository as metering
from app.modules.reconcile import service as reconcile

A = uuid.uuid4()
NOW = datetime(2026, 11, 10)
DAY = date(2026, 11, 10)
CURSOR = {"before_at": NOW, "before_id": A}

QUERIES = {
    "claim next due event (worker)": (inbox.CLAIM_DUE, {"lease": 60}),
    "duplicate check on insert": (inbox.SELECT_EXISTING, ("evt",)),
    "load a call's events": (metering.LOAD_EVENTS, ("acct_001", "call")),
    "lock a call": (metering.LOCK_CALL, (A, "call")),
    "ensure call row": (metering.ENSURE_CALL, (A, "call")),
    "read buckets": (aggregates.READ_BUCKETS, (["day"], [DAY], A)),
    "read series": (aggregates.READ_SERIES, (A, "day", DAY, DAY, 100)),
    "read an account's aggregates": (aggregates.READ_ACCOUNT, (A,)),
    "read month for many accounts": (aggregates.READ_MONTH_MANY, ([A], DAY)),
    "recent calls": (metering.LIST_CALLS.format(cursor=""), {"account_id": A, "limit": 10}),
    "recent calls (next page)": (
        metering.LIST_CALLS.format(cursor="AND (ended_at, id) < (%(before_at)s, %(before_id)s)"),
        {"account_id": A, "limit": 10, **CURSOR},
    ),
    "account by external id": ("SELECT * FROM accounts WHERE external_id = %s", ("acct_001",)),
    "account list (live)": (
        "SELECT * FROM accounts WHERE deleted_at IS NULL AND external_id > %s "
        "ORDER BY external_id LIMIT 50",
        ("",),
    ),
    "account list (deleted)": (
        "SELECT * FROM accounts WHERE deleted_at IS NOT NULL AND external_id > %s "
        "ORDER BY external_id LIMIT 50",
        ("",),
    ),
    "metrics: pending count": (
        "SELECT count(*) FROM call_events WHERE status = 'pending' AND deleted_at IS NULL",
        (),
    ),
    "metrics: dead count": (
        "SELECT count(*) FROM call_events WHERE status = 'dead' AND deleted_at IS NULL",
        (),
    ),
    "metrics: oldest due": (
        "SELECT min(next_attempt_at) FROM call_events "
        "WHERE status = 'pending' AND deleted_at IS NULL",
        (),
    ),
    "reconcile: stream events": (reconcile.STREAM_EVENTS, ("acct_001",)),
    "reconcile: retire orphan calls": (reconcile.RETIRE_ORPHAN_CALLS, (A, "acct_001")),
    "console: events by status": (
        "SELECT * FROM call_events WHERE deleted_at IS NULL AND status = 'dead' "
        "ORDER BY received_at DESC, id DESC LIMIT 25",
        (),
    ),
    "console: events by status (next page)": (
        "SELECT * FROM call_events WHERE deleted_at IS NULL AND status = 'dead' "
        "AND (received_at, id) < (%(before_at)s, %(before_id)s) "
        "ORDER BY received_at DESC, id DESC LIMIT 25",
        CURSOR,
    ),
    "console: events by account": (
        "SELECT * FROM call_events WHERE deleted_at IS NULL AND account_external_id = 'acct_001' "
        "ORDER BY received_at DESC, id DESC LIMIT 25",
        (),
    ),
    "console: events by account and status": (
        "SELECT * FROM call_events WHERE deleted_at IS NULL AND account_external_id = 'acct_001' "
        "AND status = 'dead' ORDER BY received_at DESC, id DESC LIMIT 25",
        (),
    ),
    "console: voided events": (
        "SELECT * FROM call_events WHERE deleted_at IS NOT NULL "
        "ORDER BY received_at DESC, id DESC LIMIT 25",
        (),
    ),
    "verify: calls of a run": (metering.READ_CALLS, ("acct_001", ["c1", "c2"])),
    "verify: waiting events of a run": (metering.COUNT_WAITING, ("acct_001", ["c1", "c2"])),
    "audit: newest": (audit.RECENT.format(filters=""), {"limit": 50}),
    "audit: one target": (
        audit.RECENT.format(filters=" AND target = %(target)s"),
        {"limit": 50, "target": "acct_001"},
    ),
    "fleet: recent traffic": (fleet.READ_OUTCOMES, (30,)),
    "fleet: running processes": (fleet.READ_INSTANCES, ()),
    "fleet: heartbeat": (fleet.HEARTBEAT, ("i", "api", "{}")),
    "jobs: claim": (jobs.CLAIM_JOB, ()),
    "console: event by id": ("SELECT * FROM call_events WHERE id = %s", (A,)),
    "console: requeue all dead": (
        "UPDATE call_events SET status = 'pending' WHERE status = 'dead' AND deleted_at IS NULL",
        (),
    ),
}


EXPECTED_INDEX = {
    "verify: calls of a run": "calls_live_key",
    "verify: waiting events of a run": ("call_events_by_call", "call_events_due"),
    "audit: newest": "audit_log_recent",
    "audit: one target": "audit_log_by_target",
    "fleet: recent traffic": "webhook_stats_live_key",
    "fleet: running processes": "service_instances_seen",
    "fleet: heartbeat": "service_instances_instance_key",
    "jobs: claim": "scheduled_jobs_due",
    "claim next due event (worker)": "call_events_due",
    "duplicate check on insert": "call_events_provider_event_id_key",
    "load a call's events": "call_events_by_call",
    "lock a call": "calls_live_key",
    "ensure call row": "calls_live_key",
    "read buckets": "usage_aggregate_live_key",
    "read series": "usage_aggregate_live_key",
    "read an account's aggregates": "usage_aggregate_live_key",
    "read month for many accounts": "usage_aggregate_live_key",
    "recent calls": "calls_recent",
    "recent calls (next page)": "calls_recent",
    "account by external id": "accounts_external_id_key",
    "account list (live)": "accounts_external_id_key",
    "account list (deleted)": "accounts_deleted",
    "metrics: pending count": "call_events_due",
    "metrics: dead count": "call_events_by_status",
    "metrics: oldest due": "call_events_due",
    "reconcile: stream events": "call_events_by_call",
    "reconcile: retire orphan calls": "call_events_by_call",
    "console: events by status": "call_events_by_status",
    "console: events by status (next page)": "call_events_by_status",
    "console: events by account": "call_events_by_account",
    "console: events by account and status": ("call_events_by_account", "call_events_by_status"),
    "console: voided events": "call_events_voided",
    "console: event by id": "call_events_pkey",
    "console: requeue all dead": "call_events_by_status",
}


ROWS = 6000


@pytest.fixture
def populated(conn):
    """A skewed table, as in production: almost everything processed, a few pending or dead.
    Without statistics the planner guesses and may pick an arbitrary index."""
    conn.execute(
        """
        INSERT INTO call_events (provider_event_id, account_external_id, provider_call_id,
          event_type, occurred_at, received_at, duration_seconds, cost_cents,
          destination_country, raw_body, status, next_attempt_at)
        SELECT 'evt_' || n, 'acct_00' || (1 + mod(n, 3)), 'call_' || n, 'call.ended',
               now() - (n || ' seconds')::interval, now() - (n || ' seconds')::interval, 60, 2,
               'US', ''::bytea,
               CASE WHEN mod(n, 50) = 0 THEN 'pending'
                    WHEN mod(n, 97) = 0 THEN 'dead' ELSE 'processed' END,
               now() - (n || ' seconds')::interval
        FROM generate_series(1, %s) AS n
        """,
        (ROWS,),
    )
    conn.execute("UPDATE call_events SET deleted_at = now() WHERE provider_event_id LIKE '%%7'")
    conn.commit()
    conn.execute(
        "INSERT INTO audit_log (action, target, actor, created_at) "
        "SELECT 'x', 'acct_' || mod(n, 50), 'console', now() - (n || ' seconds')::interval "
        "FROM generate_series(1, 3000) AS n"
    )
    conn.execute(
        "INSERT INTO webhook_stats (bucket_start, outcome, requests) "
        "SELECT date_trunc('minute', now()) - (n || ' minutes')::interval, 'accepted', 1 "
        "FROM generate_series(1, 3000) AS n"
    )
    conn.execute(
        "INSERT INTO service_instances (instance, role, last_seen_at) SELECT 'worker:' || n, "
        "'worker', now() - (n || ' minutes')::interval FROM generate_series(1, 2000) AS n"
    )
    conn.commit()
    for table in ("call_events", "audit_log", "webhook_stats", "service_instances"):
        conn.execute(f"ANALYZE {table}")
    conn.commit()


@pytest.mark.parametrize("name", QUERIES)
def test_query_uses_its_intended_index(conn, populated, name):
    """Not just "no seq scan" (a full scan of some other index would also pass that):
    the plan must use the index this query was designed around."""
    sql, params = QUERIES[name]
    conn.execute("SET LOCAL enable_seqscan = off")
    plan = "\n".join(
        next(iter(r.values())) for r in conn.execute("EXPLAIN " + sql, params).fetchall()
    )
    assert "Seq Scan" not in plan, plan
    allowed = EXPECTED_INDEX[name]
    allowed = (allowed,) if isinstance(allowed, str) else allowed
    assert any(index in plan for index in allowed), plan
    conn.rollback()


def test_every_query_has_an_expected_index():
    assert set(QUERIES) == set(EXPECTED_INDEX)
