"""Pool behaviour that production depends on: bounded waiting, fast failure, visibility."""

import threading
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import connect
from app.main import create_app
from tests.conftest import ADMIN_KEY

ADMIN = {"Authorization": f"Bearer {ADMIN_KEY}"}


def tight(settings: Settings, **extra) -> Settings:
    base = {"db_pool_min_size": 1, "db_pool_max_size": 1, "db_pool_timeout": 0.4}
    return settings.model_copy(update={**base, **extra})


def test_a_saturated_pool_answers_503_with_retry_after_instead_of_hanging(settings, conn):
    with TestClient(create_app(tight(settings, db_pool_max_waiting=4))) as client:
        pool = client.app.state.pool
        held = pool.getconn()  # the only connection is busy
        started = time.perf_counter()
        r = client.get("/admin/v1/accounts", headers=ADMIN)
        waited = time.perf_counter() - started
        pool.putconn(held)
        assert r.status_code == 503 and r.headers["retry-after"] == "1"
        assert r.json()["error"]["code"] == "overloaded"
        assert 0.3 < waited < 2  # bounded by DB_POOL_TIMEOUT, not forever
        assert client.get("/admin/v1/accounts", headers=ADMIN).status_code == 200  # and recovers


def test_a_full_wait_queue_fails_immediately(settings, conn):
    """With one waiter already queued (max_waiting=1), the next request is refused at once."""
    with TestClient(create_app(tight(settings, db_pool_max_waiting=1, db_pool_timeout=3))) as c:
        pool = c.app.state.pool
        held = pool.getconn()
        first = threading.Thread(target=lambda: c.get("/admin/v1/accounts", headers=ADMIN))
        first.start()
        time.sleep(0.3)  # let it join the wait queue
        started = time.perf_counter()
        r = c.get("/admin/v1/accounts", headers=ADMIN)
        waited = time.perf_counter() - started
        pool.putconn(held)
        first.join()
        assert r.status_code == 503 and r.json()["error"]["code"] == "overloaded"
        assert waited < 1  # TooManyRequests: no point queueing, say so at once


def test_a_waiting_queue_of_zero_is_refused_because_psycopg_reads_it_as_unlimited(settings):
    with pytest.raises(ValueError):
        settings.model_validate({**settings.model_dump(), "db_pool_max_waiting": 0})


def test_the_webhook_path_is_503_too_so_the_provider_redelivers(settings, conn, post_raw):
    with TestClient(create_app(tight(settings, db_pool_max_waiting=1))) as c:
        pool = c.app.state.pool
        held = pool.getconn()
        r = post_raw(c)  # waits out DB_POOL_TIMEOUT, then 503
        pool.putconn(held)
        assert r.status_code == 503 and r.headers["retry-after"] == "1"
        assert conn.execute("SELECT count(*) AS n FROM call_events").fetchone()["n"] == 0


def test_pool_statistics_are_exposed(client):
    client.get("/admin/v1/accounts", headers=ADMIN)
    client.app.state.pool.check()
    assert client.get("/admin/v1/overview", headers=ADMIN).json()["pool_max_size"] == 4
    metrics = client.get("/metrics").text
    for name in (
        "db_pool_size",
        "db_pool_available",
        "db_requests_waiting",
        "db_pool_requests_total",
        "db_pool_wait_seconds_total",
        "db_pool_requests_errors_total",
        "db_pool_connections_lost_total",
    ):
        assert name in metrics, name


def test_connections_are_labelled_and_carry_server_side_timeouts(settings, client):
    with client.app.state.pool.connection() as c:
        assert c.execute("SHOW application_name").fetchone()["application_name"] == "metering-api"
        assert c.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "30s"
        idle = c.execute("SHOW idle_in_transaction_session_timeout").fetchone()
        assert idle["idle_in_transaction_session_timeout"] == "1min"
    with connect(settings) as c:
        assert (
            c.execute("SHOW application_name").fetchone()["application_name"] == "metering-worker"
        )


def test_a_runaway_query_is_cancelled_by_the_server(settings):
    quick = settings.model_copy(update={"db_statement_timeout_ms": 200})
    with connect(quick) as c, pytest.raises(psycopg.errors.QueryCanceled):
        c.execute("SELECT pg_sleep(5)")


def test_a_transaction_left_open_is_killed_so_it_cannot_hold_locks(settings):
    short = settings.model_copy(update={"db_idle_in_transaction_timeout_ms": 300})
    c = connect(short)
    try:
        c.execute("SELECT 1")  # a transaction is now open and idle
        time.sleep(0.8)
        with pytest.raises(psycopg.errors.IdleInTransactionSessionTimeout):
            c.execute("SELECT 1")
    finally:
        c.close()
