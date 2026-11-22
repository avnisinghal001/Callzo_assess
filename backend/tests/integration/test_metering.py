import itertools
import random

from app.modules.aggregates import repository as aggregates
from app.modules.aggregates.buckets import LIFETIME_START, Bucket, Period, Usage
from tests.helpers import account_uuid, at, event


def lifetime(conn, account="acct_001") -> Usage:
    bucket = Bucket(Period.LIFETIME, LIFETIME_START)
    return aggregates.read_buckets(conn, account_uuid(conn, account), [bucket]).get(bucket, Usage())


def month_usage(conn, month, account="acct_001") -> Usage:
    bucket = Bucket(Period.MONTH, month)
    return aggregates.read_buckets(conn, account_uuid(conn, account), [bucket]).get(bucket, Usage())


def test_normal_call(post, process, conn):
    post(event("s1", "call.started", timestamp="2026-11-10T10:00:00+00:00"))
    post(event("e1", "call.ended", timestamp="2026-11-10T10:03:00+00:00", duration=180, cost=6))
    assert process() == 2
    total = lifetime(conn)
    assert (total.completed_calls, total.duration_seconds, total.cost_cents) == (1, 180, 6)


def test_a_started_call_alone_costs_nothing(post, process, conn):
    post(event("s1", "call.started"))
    process()
    assert lifetime(conn) == Usage()


def test_duplicates_never_double_count(post, process, conn):
    for _ in range(3):
        post(event("e1", duration=120, cost=4))
    process()
    assert lifetime(conn).cost_cents == 4


def test_out_of_order_equals_in_order(post, process, conn):
    post(event("e1", "call.ended", duration=60, cost=2, timestamp="2026-11-10T10:01:00+00:00"))
    process()  # ended processed with no started yet
    post(event("s1", "call.started", timestamp="2026-11-10T10:00:00+00:00"))
    process()
    total = lifetime(conn)
    assert (total.completed_calls, total.duration_seconds) == (1, 60)
    call = conn.execute("SELECT status, started_at FROM calls").fetchone()
    assert call["status"] == "completed" and call["started_at"] == at("2026-11-10T10:00:00")


def test_late_event_counts_in_the_month_it_happened_and_is_flagged(post, process, conn):
    post(event("e1", timestamp="2026-10-18T10:00:00+00:00", duration=300, cost=10))
    conn.execute("UPDATE call_events SET received_at = '2026-11-22T10:00:00+00:00'")
    conn.commit()
    process()
    from datetime import date

    assert month_usage(conn, date(2026, 11, 1)) == Usage()  # this month untouched
    october = month_usage(conn, date(2026, 10, 1))
    assert (october.cost_cents, october.late_calls, october.late_cost_cents) == (10, 1, 10)


def test_failed_call_then_late_ended_corrects_the_totals(post, process, conn):
    post(event("f1", "call.failed", timestamp="2026-11-10T10:00:00+00:00"))
    process()
    assert (lifetime(conn).failed_calls, lifetime(conn).completed_calls) == (1, 0)
    post(event("e1", timestamp="2026-11-10T10:05:00+00:00", duration=60, cost=2))
    process()
    total = lifetime(conn)
    assert (total.failed_calls, total.completed_calls, total.cost_cents) == (0, 1, 2)


def test_any_order_and_any_duplication_gives_identical_totals(post, process, conn):
    events = [event(f"s{i}", "call.started", call_id=f"c{i}") for i in range(6)] + [
        event(f"e{i}", call_id=f"c{i}", duration=60 * (i + 1), cost=i + 1) for i in range(6)
    ]
    expected = Usage(completed_calls=6, duration_seconds=60 * 21, cost_cents=21)
    for seed in range(5):
        conn.execute("TRUNCATE call_events, calls, usage_aggregate")
        conn.commit()
        shuffled = events * 2
        random.Random(seed).shuffle(shuffled)
        for payload in shuffled:
            post(payload)
        process()
        assert lifetime(conn) == expected


def test_unknown_account_is_retried_then_succeeds_once_provisioned(post, process, conn):
    post(event("e1", account_id="acct_999", duration=60, cost=2))
    assert process() == 1
    row = conn.execute("SELECT status, attempts FROM call_events").fetchone()
    assert (row["status"], row["attempts"]) == ("pending", 1)

    conn.execute("INSERT INTO accounts (external_id, monthly_cap_minutes) VALUES ('acct_999', 5)")
    conn.execute("UPDATE call_events SET next_attempt_at = now()")
    conn.commit()
    process()
    assert lifetime(conn, "acct_999").cost_cents == 2
    assert conn.execute("SELECT status FROM call_events").fetchone()["status"] == "processed"


def test_events_that_keep_failing_end_up_dead_and_can_be_requeued(post, process, conn):
    post(event("e1", account_id="acct_999"))
    for _ in range(3):  # max_attempts is 3 in tests
        conn.execute("UPDATE call_events SET next_attempt_at = now()")
        conn.commit()
        process()
    assert conn.execute("SELECT status FROM call_events").fetchone()["status"] == "dead"

    from app.modules.inbox.repository import requeue_dead

    assert requeue_dead(conn) == 1
    conn.commit()
    assert conn.execute("SELECT status, attempts FROM call_events").fetchone() == {
        "status": "pending",
        "attempts": 0,
    }


def test_a_failure_leaves_no_partial_writes(post, process, conn):
    post(event("e1", account_id="acct_999"))
    process()
    assert conn.execute("SELECT count(*) AS n FROM calls").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM usage_aggregate").fetchone()["n"] == 0


def test_cap_engages_at_the_boundary(post, process, conn, client, auth):
    """Cap is 5 minutes (300s). 299s -> allowed, exactly 300s -> reached, 301s -> exceeded."""

    def state():
        r = client.get("/v1/accounts/acct_001/usage", params={"on": "2026-11-10"}, headers=auth)
        return r.json()["cap"]

    post(event("e1", call_id="a", duration=299, cost=1))
    process()
    assert (state()["status"], state()["new_calls_allowed"]) == ("warning", True)
    assert state()["reached_at"] is None

    post(event("e2", call_id="b", duration=1, cost=1))
    process()
    assert (state()["status"], state()["new_calls_allowed"]) == ("reached", False)
    first_crossing = state()["reached_at"]
    assert first_crossing is not None

    post(event("e3", call_id="c", duration=1, cost=1))
    process()
    cap = state()
    assert (cap["status"], cap["overage_seconds"], cap["reached_at"]) == (
        "exceeded",
        1,
        first_crossing,
    )


def test_cap_is_per_account_and_per_month(post, process, conn, client, auth):
    post(event("e1", duration=400, cost=1, timestamp="2026-10-10T10:00:00+00:00"))
    process()
    caps = {
        account: client.get(
            f"/v1/accounts/{account}/usage", params={"on": "2026-11-10"}, headers=auth
        ).json()["cap"]["status"]
        for account in ("acct_001", "acct_002")
    }
    assert caps == {"acct_001": "ok", "acct_002": "ok"}  # October's overage does not leak
    october = client.get("/v1/accounts/acct_001/usage", params={"on": "2026-10-10"}, headers=auth)
    assert october.json()["cap"]["status"] == "exceeded"


def test_processing_each_event_twice_is_harmless(post, process, conn):
    post(event("e1", duration=60, cost=2))
    process()
    conn.execute("UPDATE call_events SET status = 'pending', next_attempt_at = now()")
    conn.commit()
    process()
    assert lifetime(conn).cost_cents == 2


def test_call_ids_are_scoped_to_their_account(post, process, conn):
    post(event("e1", call_id="same", account_id="acct_001", duration=60, cost=2))
    post(event("e2", call_id="same", account_id="acct_002", duration=120, cost=4))
    process()
    assert lifetime(conn, "acct_001").cost_cents == 2
    assert lifetime(conn, "acct_002").cost_cents == 4


def test_permuted_delivery_orders_all_agree(post, process, conn):
    base = [event("s", "call.started"), event("e", duration=90, cost=3), event("f", "call.failed")]
    results = set()
    for order in itertools.permutations(base):
        conn.execute("TRUNCATE call_events, calls, usage_aggregate")
        conn.commit()
        for payload in order:
            post(payload)
            process()
        results.add(lifetime(conn))
    assert len(results) == 1
