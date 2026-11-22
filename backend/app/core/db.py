"""Connections. SQL lives in each module's repository; transactions open in services/routes.

Pool sizing rule: a small pool with fast queries beats a large pool of waiting requests. Every
process owns its own pool, so total connections = processes x DB_POOL_MAX_SIZE (see README).
"""

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import Settings

Conn = psycopg.Connection[dict[str, Any]]


def connection_kwargs(settings: Settings, application_name: str) -> dict[str, Any]:
    """Per-connection settings. Timeouts are enforced by the server, so a stuck query or a
    transaction a crashed client left open cannot hold locks forever."""
    kwargs: dict[str, Any] = {
        "row_factory": dict_row,
        "connect_timeout": settings.db_connect_timeout,
        "application_name": application_name,  # visible in pg_stat_activity: who owns what
    }
    if settings.db_pgbouncer:
        kwargs["prepare_threshold"] = None
    else:
        kwargs["options"] = (
            f"-c statement_timeout={settings.db_statement_timeout_ms} "
            f"-c idle_in_transaction_session_timeout={settings.db_idle_in_transaction_timeout_ms}"
        )
    return kwargs


def make_pool(settings: Settings, application_name: str = "metering-api") -> ConnectionPool:
    pool = ConnectionPool(
        settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_pool_timeout,
        max_waiting=settings.db_pool_max_waiting,
        max_idle=settings.db_pool_max_idle,
        max_lifetime=settings.db_pool_max_lifetime,
        reconnect_timeout=settings.db_pool_reconnect_timeout,
        num_workers=settings.db_pool_num_workers,
        kwargs=connection_kwargs(settings, application_name),
        open=False,
    )
    pool.open(wait=True, timeout=30)
    return pool


def connect(
    settings: Settings, *, autocommit: bool = False, application_name: str = "metering-worker"
) -> Conn:
    """A dedicated connection, outside the pool, for the worker, the CLI and migrations."""
    return psycopg.connect(
        settings.database_url,
        autocommit=autocommit,
        **connection_kwargs(settings, application_name),
    )
