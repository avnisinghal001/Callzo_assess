import random

from app.core.config import Settings
from app.core.db import Conn
from app.core.errors import AppError, Unauthorized
from app.core.metrics import DEAD_COUNT, OLDEST_DUE, PENDING_COUNT
from app.core.security import any_signature_is_valid
from app.core.timeutil import utc_now
from app.modules.aggregates.buckets import Usage
from app.modules.audit import service as audit
from app.modules.fleet import repository as fleet
from app.modules.jobs import service as jobs
from app.modules.metering import repository as calls
from app.modules.metering.call_state import usage_of
from app.modules.ops.scenarios import (
    bad_signatures,
    build_scenario,
    expected_usage,
    malformed_bodies,
)
from app.modules.ops.schemas import (
    InboxStats,
    Instance,
    Job,
    MinuteStats,
    Overview,
    SandboxRequest,
    SandboxResponse,
    SandboxResult,
    VerifyRequest,
    VerifyResponse,
)
from app.modules.usage import service as usage
from app.modules.webhooks import service as webhooks

TRAFFIC_MINUTES = 30
ALIVE_WITHIN_SECONDS = 20


def overview(conn: Conn, settings: Settings) -> Overview:
    pending = conn.execute(PENDING_COUNT).fetchone()["n"]
    dead = conn.execute(DEAD_COUNT).fetchone()["n"]
    lag = conn.execute(OLDEST_DUE).fetchone()["lag"]
    return Overview(
        server_time=utc_now(),
        inbox=InboxStats(pending=pending, dead=dead, oldest_due_seconds=max(float(lag or 0), 0.0)),
        traffic=_traffic(conn),
        traffic_minutes=TRAFFIC_MINUTES,
        instances=[
            Instance(**row, alive=row["silent_seconds"] < ALIVE_WITHIN_SECONDS)
            for row in fleet.read_instances(conn)
        ],
        jobs=[Job(**row) for row in jobs.list_jobs(conn)],
        pool_max_size=settings.db_pool_max_size,
        sandbox_enabled=settings.enable_sandbox,
    )


def _traffic(conn: Conn) -> list[MinuteStats]:
    minutes: dict = {}
    for row in fleet.read_outcomes(conn, TRAFFIC_MINUTES):
        minutes.setdefault(row["bucket_start"], {})[row["outcome"]] = row["requests"]
    return [MinuteStats(minute=m, outcomes=o) for m, o in minutes.items()]


def run_scenario(conn: Conn, settings: Settings, request: SandboxRequest) -> SandboxResponse:
    """The real validation, signature and storage code; only the network hop is skipped."""
    if request.scenario == "malformed":
        results, call_ids, expected = _run_malformed(request.account), [], Usage()
    elif request.scenario == "bad_signature":
        results, call_ids, expected = _run_bad_signatures(settings, request.account), [], Usage()
    else:
        results, call_ids, expected = _run_stored(conn, request)
    audit.record(conn, "sandbox.run", request.account, scenario=request.scenario, sent=len(results))
    return SandboxResponse(
        scenario=request.scenario,
        account=request.account,
        sent=len(results),
        results=results,
        call_ids=call_ids,
        expected=expected,
    )


def _run_stored(
    conn: Conn, request: SandboxRequest
) -> tuple[list[SandboxResult], list[str], Usage]:
    now = utc_now()
    events = build_scenario(request.scenario, request.account, request.count, now, random.Random())
    results = []
    for parsed in events:
        stored = webhooks.store(
            conn,
            webhooks.to_new_event(parsed, "console-sandbox"),
            parsed.model_dump_json().encode(),
        )
        results.append(
            SandboxResult(
                label=parsed.event_type,
                event_id=parsed.event_id,
                call_id=parsed.call_id,
                outcome=stored.outcome,
                status_code=202 if stored.outcome == "accepted" else 200,
                metric=stored.outcome,
            )
        )
    call_ids = list(dict.fromkeys(e.call_id for e in events))
    return results, call_ids, expected_usage(events, now)


def _run_malformed(account: str) -> list[SandboxResult]:
    results = []
    for label, body in malformed_bodies(account, utc_now()):
        try:
            webhooks.parse_event(body)
        except AppError as exc:
            results.append(_rejected(label, exc))
    return results


def _run_bad_signatures(settings: Settings, account: str) -> list[SandboxResult]:
    body = malformed_bodies(account, utc_now())[0][1]
    return [
        _rejected(label, Unauthorized("Invalid signature"), metric="invalid_signature")
        for label, signature in bad_signatures(body)
        if not any_signature_is_valid(settings.webhook_secrets, body, signature)
    ]


def _rejected(label: str, error: AppError, metric: str | None = None) -> SandboxResult:
    return SandboxResult(
        label=label,
        outcome="rejected",
        status_code=error.status_code,
        metric=metric or error.code,
    )


def verify(conn: Conn, request: VerifyRequest) -> VerifyResponse:
    """What a run really contributed, read from the metered calls themselves (not from account
    totals, which other traffic may be changing at the same time)."""
    summary = usage.summary(conn, request.account, utc_now().date())
    rows = calls.read_calls(conn, request.account, request.call_ids)
    return VerifyResponse(
        waiting_events=calls.count_waiting_events(conn, request.account, request.call_ids),
        actual=sum((usage_of(state) for _, state in rows), Usage()),
        months=sorted({f"{s.usage_date:%Y-%m}" for _, s in rows if s.usage_date}),
        call_uuids=[row_id for row_id, _ in rows],
        cap=summary.cap,
    )
