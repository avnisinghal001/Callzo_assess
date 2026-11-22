from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.security import require_scope
from app.core.types import ID_PATTERN
from app.modules.audit import service
from app.modules.audit.schemas import AuditPage

router = APIRouter(
    prefix="/admin/v1/audit", tags=["admin: audit"], dependencies=[Depends(require_scope("admin"))]
)


@router.get("", response_model=AuditPage)
def list_audit(
    request: Request,
    target: Annotated[str | None, Query(pattern=ID_PATTERN)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPage:
    with request.app.state.pool.connection() as conn:
        return service.recent(conn, target, cursor, limit)
