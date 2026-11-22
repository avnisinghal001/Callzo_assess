"""Fixtures. Integration tests run against a real, throwaway Postgres database: locking and
ON CONFLICT behaviour are the point, so SQLite would prove nothing.

TEST_DATABASE_URL points at any database on a server where we may CREATE DATABASE.
"""

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app.core.config import Settings
from app.migrate import apply_migrations
from app.modules.accounts import repository as accounts

WEBHOOK_SECRET = "test-webhook-secret-0123456789"
API_KEY = "test-api-key-0123456789"
ADMIN_KEY = "test-admin-key-0123456789"
TABLES = (
    "call_events, calls, usage_aggregate, accounts, audit_log, webhook_stats, service_instances"
)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("TEST_DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    admin_url = os.environ["TEST_DATABASE_URL"]
    name = f"callzo_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(admin_url, **{**conninfo_to_dict(admin_url), "dbname": name})
    with psycopg.connect(url, row_factory=dict_row) as conn:
        apply_migrations(conn)
    yield url
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
def settings(database_url: str, tmp_path) -> Settings:
    return Settings(
        database_url=database_url,
        webhook_secret=WEBHOOK_SECRET,
        api_key=API_KEY,
        admin_api_key=ADMIN_KEY,
        enable_sandbox=True,
        max_body_bytes=4096,
        max_attempts=3,
        db_pool_max_size=4,
        db_pool_min_size=1,
        fleet_report_seconds=3600,  # tests flush explicitly
        worker_alive_file=str(tmp_path / "alive"),
    )


@pytest.fixture
def conn(database_url: str) -> Iterator[psycopg.Connection]:
    """A clean database with 3 accounts (cap 5 minutes) for each test."""
    with psycopg.connect(database_url, row_factory=dict_row) as c:
        c.execute(f"TRUNCATE {TABLES} CASCADE")
        accounts.seed(c, 3, 5)
        c.commit()
        yield c
