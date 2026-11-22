from datetime import date

from app.modules.aggregates import repository as aggregates
from app.modules.aggregates.buckets import LIFETIME_START, Bucket, Period, Usage
from app.modules.reconcile.service import reconcile_account
from tests.helpers import account_uuid, event


def seed_calls(post, process):
    post(event("s1", "call.started", call_id="a", timestamp="2026-11-10T09:00:00+00:00"))
    post(event("e1", call_id="a", timestamp="2026-11-10T10:00:00+00:00", duration=600, cost=20))
    post(event("e2", call_id="b", timestamp="2026-10-05T10:00:00+00:00", duration=300, cost=10))
    post(event("f1", "call.failed", call_id="c", timestamp="2026-11-11T10:00:00+00:00"))
    process()


def snapshot(conn):
    return (
        conn.execute(
            "SELECT * FROM usage_aggregate ORDER BY account_id, period_type, period_start"
        ).fetchall(),
        conn.execute("SELECT * FROM calls ORDER BY account_id, provider_call_id").fetchall(),
    )


def lifetime(conn) -> Usage:
    bucket = Bucket(Period.LIFETIME, LIFETIME_START)
    return aggregates.read_buckets(conn, account_uuid(conn), [bucket])[bucket]


def test_clean_data_has_no_drift_and_reconcile_changes_nothing(post, process, conn):
    seed_calls(post, process)
    before = snapshot(conn)
    report = reconcile_account(conn, "acct_001")
    conn.commit()
    assert report.drift == () and report.calls_seen == 3
    assert snapshot(conn)[0] == before[0]


def test_corrupted_totals_are_detected_and_repaired(post, process, conn):
    seed_calls(post, process)
    good = lifetime(conn)
    conn.execute(
        "UPDATE usage_aggregate SET cost_cents = cost_cents + 999 WHERE period_type = 'lifetime'"
    )
    conn.execute(
        "DELETE FROM usage_aggregate WHERE period_type = 'day' AND period_start = '2026-10-05'"
    )
    conn.commit()

    report = reconcile_account(conn, "acct_001")
    conn.commit()
    assert {(d.bucket.period.value, str(d.bucket.start)) for d in report.drift} == {
        ("lifetime", "1970-01-01"),
        ("day", "2026-10-05"),
    }
    assert report.repaired and lifetime(conn) == good
    assert reconcile_account(conn, "acct_001").drift == ()  # second run: nothing left to fix


def test_dry_run_reports_but_writes_nothing(post, process, conn):
    seed_calls(post, process)
    conn.execute("UPDATE usage_aggregate SET cost_cents = 0 WHERE period_type = 'lifetime'")
    conn.commit()
    before = snapshot(conn)
    conn.commit()  # a snapshot check needs its own transaction
    report = reconcile_account(conn, "acct_001", dry_run=True)
    conn.commit()
    assert report.drift and not report.repaired
    assert snapshot(conn) == before


def test_deleted_derived_state_is_rebuilt_from_the_raw_events(post, process, conn):
    seed_calls(post, process)
    before = snapshot(conn)
    conn.execute("DELETE FROM usage_aggregate")
    conn.execute("DELETE FROM calls")
    conn.commit()
    reconcile_account(conn, "acct_001")
    conn.commit()
    after = snapshot(conn)
    # Row ids and timestamps are new, and the original first-crossing time of a cap lived only in
    # the deleted row; everything else must match exactly.
    volatile = {"id", "created_at", "updated_at", "cap_reached_at", "metadata"}

    def strip(rows):
        return [{k: v for k, v in r.items() if k not in volatile} for r in rows]

    assert strip(after[0]) == strip(before[0]) and strip(after[1]) == strip(before[1])
    assert [r["cap_reached_at"] is None for r in after[0]] == [
        r["cap_reached_at"] is None for r in before[0]
    ]


def test_reconcile_counts_events_still_waiting_in_the_inbox(post, conn):
    post(event("e1", duration=60, cost=2))  # accepted, never processed
    reconcile_account(conn, "acct_001")
    conn.commit()
    assert lifetime(conn).cost_cents == 2


def test_cap_first_crossing_time_survives_a_repair(post, process, conn):
    """Repairs are in place and only where wrong, so unrelated fields (the cap-crossing time of
    the month row) are never disturbed."""
    post(event("e1", duration=400, cost=1, timestamp="2026-11-10T10:00:00+00:00"))
    process()
    acct = account_uuid(conn)
    before = aggregates.read_month_cap_reached_at(conn, acct, date(2026, 11, 1))
    conn.execute("UPDATE usage_aggregate SET cost_cents = 5 WHERE period_type = 'lifetime'")
    conn.commit()
    reconcile_account(conn, "acct_001")
    conn.commit()
    after = aggregates.read_month_cap_reached_at(conn, acct, date(2026, 11, 1))
    assert before is not None and after == before
