"""Applies migrations/*.sql in order, once each, then seeds the 10 simulator accounts.

Plain SQL files and a tiny runner: nothing to learn beyond SQL, and safe to run repeatedly.
Each applied file's SHA-256 is recorded; editing an already-applied migration is refused,
because the database would silently differ from what the file says.

Usage: python -m app.migrate
"""

import hashlib
from pathlib import Path

import structlog
from psycopg.types.json import Jsonb

from app.core.config import load_settings
from app.core.db import Conn, connect
from app.core.logging import configure_logging
from app.modules.accounts import repository as accounts

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
SEEDED_ACCOUNTS = 10  # acct_001 .. acct_010, per the webhook spec
MIGRATION_LOCK_KEY = 7154001

log = structlog.get_logger()

# Same conventions as every other table; its updated_at trigger is added by 001_init.sql.
BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL UNIQUE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  deleted_at  timestamptz,
  metadata    jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(metadata) = 'object')
)
"""


class MigrationChecksumError(RuntimeError):
    pass


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_migrations(conn: Conn) -> list[str]:
    applied_now: list[str] = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_KEY,))
        conn.execute(BOOTSTRAP)
        done = {
            r["name"]: r["metadata"].get("sha256")
            for r in conn.execute(
                "SELECT name, metadata FROM schema_migrations WHERE deleted_at IS NULL"
            ).fetchall()
        }
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            checksum = _checksum(path)
            if path.name in done:
                if done[path.name] != checksum:
                    raise MigrationChecksumError(
                        f"{path.name} was edited after it was applied; add a new migration instead"
                    )
                continue
            conn.execute(path.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (name, metadata) VALUES (%s, %s)",
                (path.name, Jsonb({"sha256": checksum})),
            )
            applied_now.append(path.name)
    return applied_now


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    with connect(settings) as conn:
        applied = apply_migrations(conn)
        with conn.transaction():
            accounts.seed(conn, SEEDED_ACCOUNTS, settings.default_monthly_cap_minutes)
    log.info("migrations_done", applied=applied)


if __name__ == "__main__":
    main()
