from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core.security import require_scope
from app.core.types import AccountIdPath
from app.modules.aggregates.buckets import Usage
from app.modules.audit import service as audit
from app.modules.reconcile.service import reconcile_account

router = APIRouter(
    prefix="/admin/v1/accounts",
    tags=["admin: reconcile"],
    dependencies=[Depends(require_scope("admin"))],
)


class DriftOut(BaseModel):
    period: str
    start: date
    stored: Usage
    expected: Usage


class ReconcileOut(BaseModel):
    account_id: str
    calls_seen: int
    dry_run: bool
    repaired: bool
    drift: list[DriftOut]


@router.post("/{external_id}/reconcile", response_model=ReconcileOut)
def reconcile(request: Request, external_id: AccountIdPath, dry_run: bool = True) -> Any:
    """Recompute from raw events. Dry run by default: pass dry_run=false to repair."""
    with request.app.state.pool.connection() as conn:
        report = reconcile_account(conn, external_id, dry_run=dry_run)
        if not dry_run:
            audit.record(
                conn,
                "reconcile.repair",
                external_id,
                drifted_buckets=len(report.drift),
                calls_seen=report.calls_seen,
            )
    return ReconcileOut(
        account_id=report.account_id,
        calls_seen=report.calls_seen,
        dry_run=dry_run,
        repaired=report.repaired,
        drift=[
            DriftOut(
                period=d.bucket.period.value,
                start=d.bucket.start,
                stored=d.stored,
                expected=d.expected,
            )
            for d in report.drift
        ],
    )
