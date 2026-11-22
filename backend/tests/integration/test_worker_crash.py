"""A worker can die at any moment. Nothing may be lost, double counted, or retried forever."""

import psycopg
from psycopg.rows import dict_row

from app.modules.inbox import repository as inbox
from app.modules.metering.worker import drain, process_next
from tests.helpers import account_uuid, event


def row(conn):
    r = conn.execute(
        "SELECT status, attempts, last_error, next_attempt_at <= now() AS due FROM call_events"
    ).fetchone()
    conn.commit()
    return r


def expire_lease(conn):
    conn.execute("UPDATE call_events SET next_attempt_at = now()")
    conn.commit()


def test_claiming_leases_the_event_so_another_worker_cannot_take_it(post, conn, database_url):
    post(event("e1"))
    with psycopg.connect(database_url, row_factory=dict_row) as other:
        with conn.transaction():
            first = inbox.claim_due(conn, 60)
        with other.transaction():
            second = inbox.claim_due(other, 60)
    assert first is not None and second is None  # leased: not due again for 60s
    assert row(conn)["attempts"] == 1


def test_a_worker_that_dies_after_claiming_leaves_a_retryable_event(post, conn, process):
    post(event("e1", duration=60, cost=2))
    conn.commit()
    with conn.transaction():
        inbox.claim_due(conn, 60)  # claimed ... and the worker "crashes" here
    assert row(conn)["status"] == "pending"
    assert process() == 0  # lease still held: nothing to do yet
    expire_lease(conn)
    assert process() == 1
    final = row(conn)
    assert (final["status"], final["attempts"]) == ("processed", 2)
    total = conn.execute(
        "SELECT cost_cents FROM usage_aggregate WHERE period_type = 'lifetime'"
    ).fetchone()
    assert total["cost_cents"] == 2  # counted exactly once


def test_a_poison_event_that_always_kills_the_worker_ends_up_dead(post, conn):
    """Simulate a crash on every attempt: claim, never finish. Attempts still accumulate."""
    post(event("e1"))
    for _ in range(3):  # max_attempts is 3 in tests
        conn.commit()
        with conn.transaction():
            assert inbox.claim_due(conn, 60) is not None
        expire_lease(conn)
    assert row(conn)["attempts"] == 3
    assert drain(conn, max_attempts=3) == 1  # 4th claim exceeds the limit: marked dead, not run
    conn.commit()
    final = row(conn)
    assert final["status"] == "dead" and "gave up" in final["last_error"]
    assert conn.execute("SELECT count(*) AS n FROM calls").fetchone()["n"] == 0  # never processed


def test_failure_then_success_keeps_attempt_count_honest(post, conn, process):
    post(event("e1", account_id="acct_777", duration=60, cost=2))
    assert process() == 1
    assert row(conn)["attempts"] == 1
    conn.execute("INSERT INTO accounts (external_id, monthly_cap_minutes) VALUES ('acct_777', 5)")
    expire_lease(conn)
    process()
    final = row(conn)
    assert (final["status"], final["attempts"]) == ("processed", 2)
    assert account_uuid(conn, "acct_777")


def test_process_next_is_a_noop_when_idle(conn):
    conn.commit()
    assert process_next(conn, max_attempts=3) is False
