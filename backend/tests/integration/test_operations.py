"""Running on many servers: shared statistics, heartbeats, scheduled jobs, audit, rotation."""

import threading
import time

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core.middleware import _SAFE_ID
from app.main import create_app
from app.modules.fleet import repository as fleet
from app.modules.fleet.reporter import FleetReporter
from app.modules.jobs import service as jobs
from app.modules.metering import worker
from tests.helpers import at, body_of, event, sign

ADMIN = "/admin/v1"


def make_due(conn, name):
    conn.execute("UPDATE scheduled_jobs SET next_run_at = now() + interval '1 hour'")
    conn.execute("UPDATE scheduled_jobs SET next_run_at = now() WHERE name = %s", (name,))
    conn.commit()


# ---- shared statistics -------------------------------------------------------------------


def test_outcomes_from_several_servers_add_up(conn, database_url):
    minute = at("2026-11-10T10:00:00")

    def server():
        with psycopg.connect(database_url, row_factory=dict_row) as c:
            for _ in range(20):
                counts = {(minute, "duplicate"): 1, (minute, "accepted"): 2}
                fleet.add_outcomes(c, counts)
                c.commit()

    threads = [threading.Thread(target=server) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    rows = conn.execute("SELECT outcome, requests FROM webhook_stats ORDER BY 1").fetchall()
    assert [(r["outcome"], r["requests"]) for r in rows] == [("accepted", 200), ("duplicate", 100)]


def test_counts_survive_a_database_outage(client):
    class Down:
        def connection(self):
            raise psycopg.OperationalError("down")

    pool = client.app.state.pool
    reporter = FleetReporter(Down(), dict, every=60)
    reporter.count("accepted")
    reporter.flush()  # fails, keeps the count
    reporter.count("accepted")
    reporter._pool = pool
    reporter.flush()
    with pool.connection() as c:
        assert c.execute("SELECT sum(requests) AS n FROM webhook_stats").fetchone()["n"] == 2


def test_an_api_server_signs_off_on_shutdown(settings, conn):
    with TestClient(create_app(settings)) as c:
        c.app.state.reporter.flush()
        assert len(fleet.read_instances(conn)) == 1
        conn.commit()
    assert fleet.read_instances(conn) == []


# ---- worker ------------------------------------------------------------------------------


def test_worker_processes_beats_and_stops_cleanly(settings, conn, post):
    post(event("e1", duration=60, cost=2))
    stop = threading.Event()
    thread = threading.Thread(target=worker.run, args=(settings, stop))
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        conn.commit()
        if conn.execute("SELECT status FROM call_events").fetchone()["status"] == "processed":
            break
        time.sleep(0.05)
    conn.commit()
    roles = [i["role"] for i in fleet.read_instances(conn)]
    assert "worker" in roles
    from pathlib import Path

    assert Path(settings.worker_alive_file).exists()  # what the container health check reads
    stop.set()
    thread.join(timeout=5)
    conn.commit()
    assert not thread.is_alive()
    assert "worker" not in [i["role"] for i in fleet.read_instances(conn)]


# ---- scheduled jobs ----------------------------------------------------------------------


def test_a_worker_keeps_committing_after_the_reconcile_job(settings, conn, post, database_url):
    """A job that leaves a transaction open would turn every later commit into a savepoint."""
    conn.execute("UPDATE scheduled_jobs SET next_run_at = now() WHERE name = 'reconcile_check'")
    conn.commit()
    stop = threading.Event()
    thread = threading.Thread(target=worker.run, args=(settings, stop))
    thread.start()
    try:
        with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as watch:

            def becomes_true(sql: str) -> bool:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if watch.execute(sql).fetchone()["ok"]:
                        return True
                    time.sleep(0.05)
                return False

            assert becomes_true(
                "SELECT metadata @> '{\"ok\": true}' AS ok FROM scheduled_jobs "
                "WHERE name = 'reconcile_check'"
            )
            post(event("evt_after_job"))
            assert becomes_true(
                "SELECT count(*) = 1 AS ok FROM call_events WHERE status = 'processed'"
            )
    finally:
        stop.set()
        thread.join(10)


def test_the_reconcile_job_leaves_no_transaction_open(conn, settings):
    jobs.reconcile_check(conn, settings)
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


def test_exactly_one_of_many_workers_runs_a_due_job(conn, database_url, settings, monkeypatch):
    ran = []
    monkeypatch.setitem(jobs.JOBS, "retention", lambda c, s: ran.append(1) or {})
    make_due(conn, "retention")

    def one_worker():
        with psycopg.connect(database_url, row_factory=dict_row) as c:
            jobs.run_due_job(c, settings)

    threads = [threading.Thread(target=one_worker) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ran) == 1


def test_the_reconcile_job_reports_drift_but_repairs_nothing(conn, settings, post, process):
    post(event("e1", duration=60, cost=2))
    process()
    conn.execute("UPDATE usage_aggregate SET cost_cents = 99 WHERE period_type = 'lifetime'")
    make_due(conn, "reconcile_check")
    assert jobs.run_due_job(conn, settings) == "reconcile_check"
    result = conn.execute(
        "SELECT metadata FROM scheduled_jobs WHERE name = 'reconcile_check'"
    ).fetchone()["metadata"]
    assert result["ok"] and result["accounts_drifted"] == ["acct_001"]
    stored = conn.execute(
        "SELECT cost_cents FROM usage_aggregate WHERE period_type = 'lifetime'"
    ).fetchone()
    assert stored["cost_cents"] == 99
    audit = conn.execute("SELECT action, actor FROM audit_log").fetchall()
    assert audit == [{"action": "reconcile.drift_found", "actor": "scheduler"}]


def test_a_failing_job_is_recorded_and_scheduled_again(conn, settings, monkeypatch):
    def boom(c, s):
        raise RuntimeError("no")

    monkeypatch.setitem(jobs.JOBS, "retention", boom)
    make_due(conn, "retention")
    assert jobs.run_due_job(conn, settings) == "retention"
    row = conn.execute(
        "SELECT metadata, next_run_at > now() AS later FROM scheduled_jobs WHERE name = 'retention'"
    ).fetchone()
    assert row["metadata"]["error"] == "RuntimeError" and row["later"]


def test_retention_removes_only_old_telemetry(conn, settings):
    fleet.add_outcomes(conn, {(at("2020-01-01T00:00:00"), "accepted"): 1})
    conn.execute(
        "INSERT INTO webhook_stats (bucket_start, outcome, requests) "
        "VALUES (date_trunc('minute', now()), 'accepted', 1)"
    )
    make_due(conn, "retention")
    jobs.run_due_job(conn, settings)
    assert conn.execute("SELECT count(*) AS n FROM webhook_stats").fetchone()["n"] == 1


# ---- audit -------------------------------------------------------------------------------


def test_changes_are_audited_with_request_id_and_no_secret(client, admin):
    headers = {**admin, "X-Request-ID": "trace-me-12345"}
    r = client.patch(f"{ADMIN}/accounts/acct_001", headers=headers, json={"monthly_cap_minutes": 9})
    assert r.headers["x-request-id"] == "trace-me-12345"
    entry = client.get(f"{ADMIN}/audit?target=acct_001", headers=admin).json()["items"][0]
    assert entry["action"] == "account.update" and entry["request_id"] == "trace-me-12345"
    assert (entry["metadata"]["cap_before"], entry["metadata"]["cap_after"]) == (5, 9)
    assert entry["actor"].startswith("admin:") and "test-admin-key" not in str(entry)


def test_a_change_that_fails_leaves_no_audit_entry(client, admin, conn):
    client.post(
        f"{ADMIN}/accounts",
        headers=admin,
        json={"external_id": "acct_001", "monthly_cap_minutes": 1},
    )  # already exists
    assert conn.execute("SELECT count(*) AS n FROM audit_log").fetchone()["n"] == 0


def test_audit_paginates(client, admin):
    for cap in range(5):
        client.patch(f"{ADMIN}/accounts/acct_001", headers=admin, json={"monthly_cap_minutes": cap})
    first = client.get(f"{ADMIN}/audit?limit=3", headers=admin).json()
    rest = client.get(f"{ADMIN}/audit?limit=3&cursor={first['next_cursor']}", headers=admin).json()
    caps = [e["metadata"]["cap_after"] for e in first["items"] + rest["items"]]
    assert caps == [4, 3, 2, 1, 0] and rest["next_cursor"] is None


def test_lowering_the_cap_below_current_usage_marks_it_reached(client, admin, post, process):
    import datetime as dt

    now = dt.datetime.now(dt.UTC).isoformat()
    post(event("e1", duration=200, cost=1, timestamp=now))  # cap is 300 s: fine
    process()
    url = "/v1/accounts/acct_001/usage"
    assert client.get(url, headers=admin).json()["cap"]["reached_at"] is None
    client.patch(f"{ADMIN}/accounts/acct_001", headers=admin, json={"monthly_cap_minutes": 1})
    cap = client.get(url, headers=admin).json()["cap"]
    assert cap["status"] == "exceeded" and cap["reached_at"] is not None


# ---- rotation, request ids, latency ------------------------------------------------------


def test_old_and_new_secrets_both_work_during_rotation(settings, conn):
    rotating = settings.model_copy(
        update={
            "webhook_secret": "brand-new-webhook-secret",
            "webhook_secret_previous": settings.webhook_secret,
            "admin_api_key": "brand-new-admin-key-123",
            "admin_api_key_previous": settings.admin_api_key,
        }
    )
    with TestClient(create_app(rotating)) as c:
        for i, secret in enumerate([rotating.webhook_secret, rotating.webhook_secret_previous]):
            body = body_of(event(f"rot{i}"))
            r = c.post("/webhooks/calls", content=body, headers={"X-Signature": sign(body, secret)})
            assert r.status_code == 202
        for key in (rotating.admin_api_key, rotating.admin_api_key_previous):
            r = c.get(f"{ADMIN}/accounts", headers={"Authorization": f"Bearer {key}"})
            assert r.status_code == 200
        body = body_of(event("rot9"))
        bad = c.post(
            "/webhooks/calls",
            content=body,
            headers={"X-Signature": sign(body, "some-other-secret-value")},
        )
        assert bad.status_code == 401


def test_every_response_has_a_request_id_and_hostile_ones_are_replaced(client):
    assert _SAFE_ID.match(client.get("/health/live").headers["x-request-id"])
    evil = client.get("/health/live", headers={"X-Request-ID": "bad id\tinjected"})
    assert _SAFE_ID.match(evil.headers["x-request-id"])


def test_latency_is_measured_per_route_template_not_per_url(client, admin):
    for n in ("acct_001", "acct_002"):
        client.get(f"/v1/accounts/{n}/usage", headers=admin)
    text = client.get("/metrics").text
    assert "http_request_duration_seconds_count" in text
    assert 'route="/v1/accounts/{account_id}/usage"' in text
    assert "acct_001" not in text  # unbounded label values would blow up the metrics store
