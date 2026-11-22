import random
import threading
import uuid

import psycopg
from psycopg.rows import dict_row

from app.modules.aggregates import repository as aggregates
from app.modules.aggregates.buckets import LIFETIME_START, Bucket, Period
from app.modules.inbox import repository as inbox
from app.modules.inbox.models import NewEvent
from app.modules.metering.worker import drain
from app.modules.reconcile.service import reconcile_account
from tests.helpers import account_uuid, at


def new_event(event_id, kind, account, call, minute, duration=0, cost=0):
    return NewEvent(
        event_id, kind, account, call, at(f"2026-11-10T10:{minute:02}:00"), duration, cost, "US"
    )


def test_many_workers_one_account_exact_totals_and_no_deadlock(conn, database_url):
    calls = 150
    events, expected = [], 0
    for i in range(calls):
        cost = random.Random(i).randrange(1, 9)
        expected += cost
        events.append(new_event(f"s{i}", "call.started", "acct_001", f"c{i}", 0))
        events.append(new_event(f"e{i}", "call.ended", "acct_001", f"c{i}", 1, 60, cost))
    events = events * 2  # every event delivered twice
    random.Random(1).shuffle(events)
    for e in events:
        inbox.insert_event(conn, e, b"{}")
    conn.commit()

    errors: list[Exception] = []

    def worker():
        try:
            with psycopg.connect(database_url, row_factory=dict_row) as c:
                drain(c, max_attempts=3)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert errors == []
    bucket = Bucket(Period.LIFETIME, LIFETIME_START)
    total = aggregates.read_buckets(conn, account_uuid(conn), [bucket])[bucket]
    assert (total.completed_calls, total.cost_cents) == (calls, expected)
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM call_events WHERE status <> 'processed'"
        ).fetchone()["n"]
        == 0
    )
    # The incremental totals must equal a from-scratch rebuild.
    conn.commit()
    assert reconcile_account(conn, "acct_001", dry_run=True).drift == ()


def test_a_clean_check_never_waits_for_metering(conn, database_url):
    """The dry run reads a snapshot without locks: a busy account is not slowed down by it."""
    holder = psycopg.connect(database_url, row_factory=dict_row)
    holder.execute("SELECT 1 FROM accounts WHERE external_id = 'acct_001' FOR SHARE")
    conn.commit()
    conn.execute("SET lock_timeout = '300ms'")
    conn.commit()
    assert reconcile_account(conn, "acct_001", dry_run=True).drift == ()
    holder.close()


def test_reconcile_waits_for_in_flight_metering(conn, database_url):
    """A worker holding the account share-lock blocks reconcile until it commits."""
    inbox.insert_event(conn, new_event("e1", "call.ended", "acct_001", "c1", 1, 60, 2), b"{}")
    conn.commit()
    holder = psycopg.connect(database_url, row_factory=dict_row)
    holder.execute("SELECT 1 FROM accounts WHERE external_id = 'acct_001' FOR SHARE")
    finished = threading.Event()

    def run_reconcile():
        with psycopg.connect(database_url, row_factory=dict_row) as c:
            reconcile_account(c, "acct_001")
        finished.set()

    thread = threading.Thread(target=run_reconcile)
    thread.start()
    assert not finished.wait(0.5)  # blocked behind the worker
    holder.commit()
    holder.close()
    assert finished.wait(5)
    thread.join()


def test_claims_never_overlap(conn, database_url):
    for i in range(4):
        inbox.insert_event(
            conn, new_event(f"e{i}", "call.ended", "acct_001", f"c{i}", 1, 60, 1), b"{}"
        )
    conn.commit()
    with (
        psycopg.connect(database_url, row_factory=dict_row) as a,
        psycopg.connect(database_url, row_factory=dict_row) as b,
    ):
        first = inbox.claim_due(a, 60)
        second = inbox.claim_due(b, 60)  # a still holds its row lock
        assert first and second and first.id != second.id


def test_two_events_of_one_call_are_serialized_not_double_counted(conn, database_url):
    """Deterministic: while one worker holds the call's row lock, a second worker handling a
    different event of the same call must wait. Without the lock both would read the same
    'previous' state and both would add the same delta."""
    from app.modules.inbox.models import InboxEvent
    from app.modules.metering import repository as calls
    from app.modules.metering.service import apply_event

    inbox.insert_event(conn, new_event("s1", "call.started", "acct_001", "c1", 0), b"{}")
    inbox.insert_event(conn, new_event("e1", "call.ended", "acct_001", "c1", 1, 60, 2), b"{}")
    conn.commit()

    holder = psycopg.connect(database_url, row_factory=dict_row)
    acct = account_uuid(conn)
    calls.ensure_call(holder, acct, "c1")
    holder.commit()  # the row exists, so only the row lock (not an insert conflict) can block B
    calls.lock_call(holder, acct, "c1")  # worker A is mid-way through this call
    finished = threading.Event()

    def worker_b():
        with psycopg.connect(database_url, row_factory=dict_row) as c:
            apply_event(c, InboxEvent(uuid.uuid4(), "e1", "call.ended", "acct_001", "c1", 1))
        finished.set()

    thread = threading.Thread(target=worker_b)
    thread.start()
    assert not finished.wait(0.5)  # B is waiting on A's lock
    holder.commit()
    holder.close()
    assert finished.wait(5)
    thread.join()

    bucket = Bucket(Period.LIFETIME, LIFETIME_START)
    total = aggregates.read_buckets(conn, account_uuid(conn), [bucket])[bucket]
    assert (total.completed_calls, total.cost_cents) == (1, 2)
