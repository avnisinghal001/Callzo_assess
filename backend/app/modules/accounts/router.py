from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.security import require_scope
from app.core.types import AccountIdPath
from app.modules.accounts import service
from app.modules.accounts.schemas import AccountCreate, AccountOut, AccountPage, AccountPatch

router = APIRouter(
    prefix="/admin/v1/accounts",
    tags=["admin: accounts"],
    dependencies=[Depends(require_scope("admin"))],
)


@router.get("", response_model=AccountPage)
def list_accounts(
    request: Request,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    deleted: bool = False,
) -> AccountPage:
    with request.app.state.pool.connection() as conn:
        return service.list_accounts(conn, cursor=cursor, limit=limit, deleted=deleted)


@router.post("", response_model=AccountOut, status_code=201)
def create_account(request: Request, body: AccountCreate) -> AccountOut:
    with request.app.state.pool.connection() as conn:
        return service.create_account(conn, body)


@router.get("/{external_id}", response_model=AccountOut)
def get_account(request: Request, external_id: AccountIdPath) -> AccountOut:
    with request.app.state.pool.connection() as conn:
        return service.get_account(conn, external_id)


@router.patch("/{external_id}", response_model=AccountOut)
def patch_account(request: Request, external_id: AccountIdPath, body: AccountPatch) -> AccountOut:
    with request.app.state.pool.connection() as conn:
        return service.patch_account(conn, external_id, body)


@router.delete("/{external_id}", response_model=AccountOut)
def delete_account(request: Request, external_id: AccountIdPath) -> AccountOut:
    """Soft delete: the account stops metering and answering; its history is kept."""
    with request.app.state.pool.connection() as conn:
        return service.delete_account(conn, external_id)


@router.post("/{external_id}/restore", response_model=AccountOut)
def restore_account(request: Request, external_id: AccountIdPath) -> AccountOut:
    with request.app.state.pool.connection() as conn:
        return service.restore_account(conn, external_id)
