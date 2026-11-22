import pytest

from app.core.config import Settings
from app.core.db import connection_kwargs

BASE = {
    "database_url": "postgresql://x/y",
    "webhook_secret": "w" * 20,
    "api_key": "r" * 20,
    "admin_api_key": "a" * 20,
}


def settings(**extra) -> Settings:
    return Settings(**BASE, **extra)


def test_pool_defaults_follow_the_production_guidance():
    s = settings()
    assert (s.db_pool_min_size, s.db_pool_max_size) == (2, 8)
    assert (s.db_pool_timeout, s.db_pool_max_waiting) == (5.0, 32)
    assert (s.db_pool_max_idle, s.db_pool_max_lifetime) == (120.0, 1800.0)
    assert (s.db_pool_reconnect_timeout, s.db_pool_num_workers, s.db_connect_timeout) == (60, 3, 5)
    # Starlette runs sync routes in 40 threads: queued + working requests must fit in them.
    assert s.db_pool_max_size + s.db_pool_max_waiting <= 40


def test_min_cannot_exceed_max():
    with pytest.raises(ValueError, match="DB_POOL_MIN_SIZE"):
        settings(db_pool_min_size=9, db_pool_max_size=8)


def test_keys_must_differ():
    with pytest.raises(ValueError, match="must be different"):
        Settings(**{**BASE, "admin_api_key": BASE["api_key"]})


def test_server_side_timeouts_and_application_name_are_sent_on_connect():
    kwargs = connection_kwargs(settings(), "metering-api")
    assert kwargs["application_name"] == "metering-api" and kwargs["connect_timeout"] == 5
    assert "statement_timeout=30000" in kwargs["options"]
    assert "idle_in_transaction_session_timeout=60000" in kwargs["options"]
    assert "prepare_threshold" not in kwargs


def test_pgbouncer_mode_drops_session_options_and_server_side_prepares():
    kwargs = connection_kwargs(settings(db_pgbouncer=True), "metering-api")
    assert kwargs["prepare_threshold"] is None and "options" not in kwargs
