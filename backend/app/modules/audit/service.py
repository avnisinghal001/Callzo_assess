from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.core import context
from app.core.db import Conn
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.audit.schemas import AuditEntry, AuditPage

RECENT = """
SELECT id, action, target, actor, request_id, created_at, metadata FROM audit_log
WHERE deleted_at IS NULL {filters}
ORDER BY created_at DESC, id DESC LIMIT %(limit)s
"""


def record(conn: Conn, action: str, target: str | UUID, **detail: Any) -> None:
    """Call inside the transaction that makes the change: both commit or neither does."""
    conn.execute(
        "INSERT INTO audit_log (action, target, actor, request_id, metadata) "
        "VALUES (%s, %s, %s, %s, %s)",
        (action, str(target), context.actor.get(), context.request_id.get(), Jsonb(detail)),
    )


def recent(conn: Conn, target: str | None, cursor: str | None, limit: int) -> AuditPage:
    filters, params = "", {"limit": limit + 1}
    if target:
        filters += " AND target = %(target)s"
        params["target"] = target
    if cursor:
        filters += " AND (created_at, id) < (%(at)s, %(id)s)"
        params["at"], params["id"] = decode_cursor(cursor)
    rows = conn.execute(RECENT.format(filters=filters), params).fetchall()
    page, more = rows[:limit], len(rows) > limit
    next_cursor = encode_cursor(page[-1]["created_at"], page[-1]["id"]) if more else None
    return AuditPage(items=[AuditEntry(**r) for r in page], next_cursor=next_cursor)
