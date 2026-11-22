from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.core.db import Conn

COLUMNS = "id, external_id, monthly_cap_minutes, created_at, updated_at, deleted_at, metadata"


@dataclass(frozen=True)
class Account:
    id: UUID
    external_id: str
    monthly_cap_minutes: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    metadata: dict[str, Any]


def _account(row: dict | None) -> Account | None:
    return None if row is None else Account(**row)


def get(conn: Conn, external_id: str, *, include_deleted: bool = False) -> Account | None:
    sql = f"SELECT {COLUMNS} FROM accounts WHERE external_id = %s"
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    return _account(conn.execute(sql, (external_id,)).fetchone())


def lock_shared(conn: Conn, external_id: str) -> Account | None:
    """Metering takes this: many workers may hold it, reconcile cannot run meanwhile."""
    return _account(
        conn.execute(
            f"SELECT {COLUMNS} FROM accounts "
            "WHERE external_id = %s AND deleted_at IS NULL FOR SHARE",
            (external_id,),
        ).fetchone()
    )


def lock_exclusive(conn: Conn, external_id: str) -> Account | None:
    """Reconcile takes this: waits for in-flight metering, and blocks new metering until done.
    NO KEY UPDATE: does not conflict with the foreign-key checks that call inserts perform."""
    return _account(
        conn.execute(
            f"SELECT {COLUMNS} FROM accounts WHERE external_id = %s AND deleted_at IS NULL "
            "FOR NO KEY UPDATE",
            (external_id,),
        ).fetchone()
    )


def list_page(conn: Conn, *, after: str, limit: int, deleted: bool) -> list[Account]:
    """Keyset pagination on the unique external_id index; never an OFFSET, never a scan."""
    predicate = "deleted_at IS NOT NULL" if deleted else "deleted_at IS NULL"
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM accounts WHERE {predicate} AND external_id > %s "
        "ORDER BY external_id LIMIT %s",
        (after, limit),
    ).fetchall()
    return [Account(**r) for r in rows]


def insert(conn: Conn, external_id: str, cap_minutes: int, metadata: dict[str, Any]) -> Account:
    row = conn.execute(
        f"INSERT INTO accounts (external_id, monthly_cap_minutes, metadata) VALUES (%s, %s, %s) "
        f"RETURNING {COLUMNS}",
        (external_id, cap_minutes, Jsonb(metadata)),
    ).fetchone()
    return Account(**row)


def update(
    conn: Conn, external_id: str, cap_minutes: int | None, metadata_patch: dict[str, Any] | None
) -> Account | None:
    """Metadata is merged key by key; a null value removes the key."""
    return _account(
        conn.execute(
            f"""
            UPDATE accounts SET
              monthly_cap_minutes = COALESCE(%(cap)s::integer, monthly_cap_minutes),
              metadata = CASE WHEN %(patch)s::jsonb IS NULL THEN metadata
                              ELSE jsonb_strip_nulls(metadata || %(patch)s::jsonb) END
            WHERE external_id = %(external_id)s AND deleted_at IS NULL
            RETURNING {COLUMNS}
            """,
            {
                "cap": cap_minutes,
                "patch": None if metadata_patch is None else Jsonb(metadata_patch),
                "external_id": external_id,
            },
        ).fetchone()
    )


def set_deleted(conn: Conn, external_id: str, *, deleted: bool) -> Account | None:
    """Soft delete / restore. None if the account is not in the opposite state."""
    sql = (
        "UPDATE accounts SET deleted_at = now() WHERE external_id = %s AND deleted_at IS NULL"
        if deleted
        else "UPDATE accounts SET deleted_at = NULL "
        "WHERE external_id = %s AND deleted_at IS NOT NULL"
    )
    return _account(conn.execute(f"{sql} RETURNING {COLUMNS}", (external_id,)).fetchone())


def seed(conn: Conn, count: int, cap_minutes: int) -> None:
    conn.execute(
        "INSERT INTO accounts (external_id, monthly_cap_minutes, metadata) "
        "SELECT 'acct_' || lpad(n::text, 3, '0'), %s, '{\"seeded\": true}' "
        "FROM generate_series(1, %s) AS n ON CONFLICT (external_id) DO NOTHING",
        (cap_minutes, count),
    )
