import psycopg.errors
import structlog

from app.core.db import Conn
from app.core.errors import Conflict, NotFound
from app.core.timeutil import month_start, utc_now
from app.modules.accounts import repository as repo
from app.modules.accounts.schemas import (
    AccountCreate,
    AccountListItem,
    AccountOut,
    AccountPage,
    AccountPatch,
    MonthBrief,
)
from app.modules.aggregates import repository as aggregates
from app.modules.aggregates.buckets import Usage
from app.modules.audit import service as audit
from app.modules.usage.cap import cap_view

log = structlog.get_logger()


def _require(account: repo.Account | None, external_id: str) -> repo.Account:
    if account is None:
        raise NotFound(f"Unknown account {external_id}")
    return account


def list_accounts(conn: Conn, *, cursor: str | None, limit: int, deleted: bool) -> AccountPage:
    rows = repo.list_page(conn, after=cursor or "", limit=limit + 1, deleted=deleted)
    page, more = rows[:limit], len(rows) > limit
    month = month_start(utc_now().date())
    usage = aggregates.read_month_many(conn, [a.id for a in page], month)
    items = []
    for account in page:
        used = usage.get(account.id, (Usage(), None))[0].duration_seconds
        view = cap_view(used, account.monthly_cap_minutes, None)
        brief = MonthBrief(
            used_seconds=used, status=view.status, new_calls_allowed=view.new_calls_allowed
        )
        items.append(AccountListItem(**account.__dict__, month=brief))
    return AccountPage(items=items, next_cursor=page[-1].external_id if more else None)


def get_account(conn: Conn, external_id: str) -> AccountOut:
    account = repo.get(conn, external_id, include_deleted=True)
    return AccountOut(**_require(account, external_id).__dict__)


def create_account(conn: Conn, data: AccountCreate) -> AccountOut:
    try:
        account = repo.insert(conn, data.external_id, data.monthly_cap_minutes, data.metadata)
    except psycopg.errors.UniqueViolation:
        raise Conflict(
            f"Account {data.external_id} already exists (it may be deleted: restore it instead)"
        ) from None
    audit.record(conn, "account.create", account.external_id, cap=account.monthly_cap_minutes)
    log.info("account_created", account=account.external_id)
    return AccountOut(**account.__dict__)


def patch_account(conn: Conn, external_id: str, data: AccountPatch) -> AccountOut:
    before = _require(repo.lock_exclusive(conn, external_id), external_id)
    account = _require(
        repo.update(conn, external_id, data.monthly_cap_minutes, data.metadata), external_id
    )
    month = month_start(utc_now().date())
    aggregates.refresh_cap_flags(conn, account.id, [month])  # the cap may now be (un)reached
    audit.record(
        conn,
        "account.update",
        external_id,
        cap_before=before.monthly_cap_minutes,
        cap_after=account.monthly_cap_minutes,
        metadata_changed=data.metadata is not None,
    )
    log.info("account_updated", account=external_id, cap=account.monthly_cap_minutes)
    return AccountOut(**account.__dict__)


def delete_account(conn: Conn, external_id: str) -> AccountOut:
    account = _require(repo.set_deleted(conn, external_id, deleted=True), external_id)
    audit.record(conn, "account.delete", external_id)
    log.warning("account_deleted", account=external_id)
    return AccountOut(**account.__dict__)


def restore_account(conn: Conn, external_id: str) -> AccountOut:
    account = _require(repo.set_deleted(conn, external_id, deleted=False), external_id)
    audit.record(conn, "account.restore", external_id)
    log.info("account_restored", account=external_id)
    return AccountOut(**account.__dict__)
