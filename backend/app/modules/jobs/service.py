"""Recurring work, safe to run from any number of workers: claiming a job is one UPDATE that
moves next_run_at, so exactly one worker wins and nothing is held while the job runs."""

import time
from collections.abc import Callable

import structlog
from psycopg.types.json import Jsonb

from app.core import context
from app.core.config import Settings
from app.core.db import Conn
from app.modules.accounts import repository as accounts
from app.modules.audit import service as audit
from app.modules.fleet import repository as fleet
from app.modules.reconcile.service import reconcile_account

log = structlog.get_logger()

CLAIM_JOB = """
UPDATE scheduled_jobs SET next_run_at = now() + make_interval(secs => interval_seconds),
  last_run_at = now()
WHERE id = (SELECT id FROM scheduled_jobs WHERE deleted_at IS NULL AND next_run_at <= now()
            ORDER BY next_run_at LIMIT 1 FOR UPDATE SKIP LOCKED)
RETURNING id, name
"""


def _next_accounts(conn: Conn, after: str) -> list[accounts.Account]:
    with conn.transaction():  # closed before the caller goes on, even for the last, empty page
        return accounts.list_page(conn, after=after, limit=200, deleted=False)


def reconcile_check(conn: Conn, settings: Settings) -> dict:
    """Compare every account with its raw events. Reports drift; never repairs on its own."""
    checked, drifted, after = 0, [], ""
    while page := _next_accounts(conn, after):
        for account in page:
            report = reconcile_account(conn, account.external_id, dry_run=True)
            checked += 1
            if report.drift:
                drifted.append(account.external_id)
        after = page[-1].external_id
    if drifted:
        with conn.transaction():
            audit.record(conn, "reconcile.drift_found", "scheduler", accounts=drifted[:50])
    return {"accounts_checked": checked, "accounts_drifted": drifted[:50]}


def retention(conn: Conn, settings: Settings) -> dict:
    with conn.transaction():
        return fleet.prune(conn, settings.stats_retention_days, instance_days=1)


JOBS: dict[str, Callable[[Conn, Settings], dict]] = {
    "reconcile_check": reconcile_check,
    "retention": retention,
}


def run_due_job(conn: Conn, settings: Settings) -> str | None:
    """Run at most one due job. A failing job is recorded and simply runs again next interval."""
    with conn.transaction():
        job = conn.execute(CLAIM_JOB).fetchone()
    if job is None:
        return None
    context.actor.set("scheduler")
    started = time.perf_counter()
    try:
        result = {"ok": True, **JOBS[job["name"]](conn, settings)}
    except Exception as exc:
        conn.rollback()
        log.error("job_failed", job=job["name"], exc_info=exc)
        result = {"ok": False, "error": type(exc).__name__}
    result["seconds"] = round(time.perf_counter() - started, 2)
    with conn.transaction():
        conn.execute(
            "UPDATE scheduled_jobs SET metadata = %s WHERE id = %s", (Jsonb(result), job["id"])
        )
    log.info("job_done", job=job["name"], **result)
    return job["name"]


def list_jobs(conn: Conn) -> list[dict]:
    return conn.execute(
        "SELECT name, interval_seconds, next_run_at, last_run_at, metadata AS last_result "
        "FROM scheduled_jobs WHERE deleted_at IS NULL ORDER BY name"
    ).fetchall()
