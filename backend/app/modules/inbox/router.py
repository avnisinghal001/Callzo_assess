from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.core.security import require_scope
from app.core.types import ID_PATTERN
from app.modules.inbox import service
from app.modules.inbox.schemas import (
    EventDetail,
    EventOut,
    EventPage,
    EventStatusFilter,
    RequeuedCount,
    VoidRequest,
)

router = APIRouter(
    prefix="/admin/v1/events",
    tags=["admin: events"],
    dependencies=[Depends(require_scope("admin"))],
)


@router.get("", response_model=EventPage)
def list_events(
    request: Request,
    status: EventStatusFilter = "pending",
    account: Annotated[str | None, Query(pattern=ID_PATTERN)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> EventPage:
    with request.app.state.pool.connection() as conn:
        return service.list_events(conn, status=status, account=account, cursor=cursor, limit=limit)


@router.post("/requeue-dead", response_model=RequeuedCount)
def requeue_dead(
    request: Request, account: Annotated[str | None, Query(pattern=ID_PATTERN)] = None
) -> RequeuedCount:
    with request.app.state.pool.connection() as conn:
        return service.requeue_dead(conn, account)


@router.get("/{event_id}", response_model=EventDetail)
def get_event(request: Request, event_id: UUID) -> EventDetail:
    with request.app.state.pool.connection() as conn:
        return service.get_event(conn, event_id)


@router.post("/{event_id}/requeue", response_model=EventOut)
def requeue(request: Request, event_id: UUID) -> EventOut:
    with request.app.state.pool.connection() as conn:
        return service.requeue(conn, event_id)


@router.post("/{event_id}/void", response_model=EventDetail)
def void(request: Request, event_id: UUID, body: VoidRequest) -> EventDetail:
    with request.app.state.pool.connection() as conn:
        return service.void(conn, event_id, body.reason)


@router.post("/{event_id}/restore", response_model=EventDetail)
def restore(request: Request, event_id: UUID) -> EventDetail:
    with request.app.state.pool.connection() as conn:
        return service.restore(conn, event_id)
