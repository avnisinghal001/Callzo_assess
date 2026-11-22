"""Rebuild derived usage from the raw event log and compare it with what is stored.

The raw log is never modified. `calls` and `usage_aggregate` are derived: reconcile corrects
them **in place and only where they differ** (an audit note goes into the row's metadata), and
soft-deletes rows that should not exist. It never wipes and rewrites, so a bucket's cap-crossing
time and history survive. This is the one operation that reads every live event of an account,
by design, through the (account, call) index, streamed with constant memory per call.
"""

import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from operator import itemgetter

import structlog

from app.core.db import Conn
from app.core.errors import NotFound
from app.core.timeutil import utc_now
from app.modules.accounts import repository as accounts
from app.modules.accounts.repository import Account
from app.modules.aggregates import repository as aggregates
from app.modules.aggregates.buckets import Bucket, Period, Usage, buckets_for_day
from app.modules.metering.call_state import CallEvent, CallState, resolve_call, usage_of

log = structlog.get_logger()

STREAM_EVENTS = """
SELECT id, provider_call_id, provider_event_id, event_type, occurred_at, received_at,
       duration_seconds, cost_cents
FROM call_events
WHERE account_external_id = %s AND deleted_at IS NULL
ORDER BY provider_call_id
"""

# In place, and only when something actually differs.
UPSERT_CALL = """
INSERT INTO calls (account_id, provider_call_id, status, started_at, ended_at, duration_seconds,
                   cost_cents, usage_date, is_late, terminal_event_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (account_id, provider_call_id) WHERE deleted_at IS NULL DO UPDATE SET
  status = EXCLUDED.status, started_at = EXCLUDED.started_at, ended_at = EXCLUDED.ended_at,
  duration_seconds = EXCLUDED.duration_seconds, cost_cents = EXCLUDED.cost_cents,
  usage_date = EXCLUDED.usage_date, is_late = EXCLUDED.is_late,
  terminal_event_id = EXCLUDED.terminal_event_id
WHERE (calls.status, calls.started_at, calls.ended_at, calls.duration_seconds, calls.cost_cents,
       calls.usage_date, calls.is_late, calls.terminal_event_id)
  IS DISTINCT FROM
      (EXCLUDED.status, EXCLUDED.started_at, EXCLUDED.ended_at, EXCLUDED.duration_seconds,
       EXCLUDED.cost_cents, EXCLUDED.usage_date, EXCLUDED.is_late, EXCLUDED.terminal_event_id)
"""

# Calls whose events were all voided (or deleted) no longer exist.
RETIRE_ORPHAN_CALLS = """
UPDATE calls c SET deleted_at = now(),
  metadata = c.metadata || jsonb_build_object('reconcile', 'no live events')
WHERE c.account_id = %s AND c.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM call_events e
    WHERE e.account_external_id = %s AND e.provider_call_id = c.provider_call_id
      AND e.deleted_at IS NULL)
"""
CALL_BATCH = 500


@dataclass(frozen=True)
class BucketDrift:
    bucket: Bucket
    stored: Usage
    expected: Usage


@dataclass(frozen=True)
class ReconcileReport:
    account_id: str
    calls_seen: int
    drift: tuple[BucketDrift, ...]
    repaired: bool


def _call_row(account_uuid, provider_call_id: str, s: CallState) -> tuple:
    return (
        account_uuid,
        provider_call_id,
        s.status,
        s.started_at,
        s.ended_at,
        s.duration_seconds,
        s.cost_cents,
        s.usage_date,
        s.is_late,
        s.terminal_event_id,
    )


def reconcile_account(conn: Conn, external_id: str, *, dry_run: bool = False) -> ReconcileReport:
    """A check (dry run) first reads a consistent snapshot without any lock, so it never delays
    metering. Events accepted but not metered yet look like drift in a snapshot, so only if
    something differs is the answer confirmed under the account lock. Repairs always lock."""
    if dry_run:
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            account = _found(accounts.get(conn, external_id), external_id)
            report = _compare(conn, account, repair=False)
        if not report.drift:
            return _logged(report, dry_run)
    with conn.transaction():
        account = _found(accounts.lock_exclusive(conn, external_id), external_id)
        report = _compare(conn, account, repair=not dry_run)
    return _logged(report, dry_run)


def _found(account: Account | None, external_id: str) -> Account:
    if account is None:
        raise NotFound(f"Unknown account {external_id}")
    return account


def _compare(conn: Conn, account: Account, *, repair: bool) -> ReconcileReport:
    stored = aggregates.read_all(conn, account.id)
    expected: dict[Bucket, Usage] = defaultdict(Usage)
    calls_seen = 0
    rows: list[tuple] = []
    for call_id, state in _replay(conn, account.external_id):
        calls_seen += 1
        usage = usage_of(state)
        if state.usage_date is not None and not usage.is_zero():
            for bucket in buckets_for_day(state.usage_date):
                expected[bucket] = expected[bucket] + usage
        if repair:
            rows.append(_call_row(account.id, call_id, state))
            if len(rows) >= CALL_BATCH:
                _upsert_calls(conn, rows)
                rows = []
    if rows:
        _upsert_calls(conn, rows)

    drift = _find_drift(stored, expected)
    if repair:
        conn.execute(RETIRE_ORPHAN_CALLS, (account.id, account.external_id))
        if drift:
            _repair_aggregates(conn, account.id, drift)
    return ReconcileReport(account.external_id, calls_seen, tuple(drift), repair and bool(drift))


def _replay(conn: Conn, external_id: str) -> Iterator[tuple[str, CallState]]:
    """Every call of the account, resolved from its raw events. Streams: constant memory."""
    with conn.cursor(name="reconcile_events") as events:
        events.itersize = 2000
        events.execute(STREAM_EVENTS, (external_id,))
        for call_id, rows in groupby(events, key=itemgetter("provider_call_id")):
            yield (
                call_id,
                resolve_call(
                    [
                        CallEvent(**{k: v for k, v in r.items() if k != "provider_call_id"})
                        for r in rows
                    ]
                ),
            )


def _logged(report: ReconcileReport, dry_run: bool) -> ReconcileReport:
    log.info(
        "reconcile_done",
        account=report.account_id,
        calls_seen=report.calls_seen,
        drifted_buckets=len(report.drift),
        dry_run=dry_run,
        repaired=report.repaired,
    )
    for item in report.drift:
        log.warning(
            "reconcile_drift",
            account=report.account_id,
            period=item.bucket.period.value,
            start=item.bucket.start.isoformat(),
            stored=item.stored.__dict__,
            expected=item.expected.__dict__,
        )
    return report


def _upsert_calls(conn: Conn, rows: list[tuple]) -> None:
    with conn.cursor() as cur:
        cur.executemany(UPSERT_CALL, rows)


def _find_drift(
    stored: dict[Bucket, tuple[Usage, datetime | None]], expected: dict[Bucket, Usage]
) -> list[BucketDrift]:
    """A missing bucket and an all-zero bucket are the same thing."""
    zero = Usage()
    drift = []
    for bucket in sorted(set(stored) | set(expected)):
        have = stored[bucket][0] if bucket in stored else zero
        want = expected.get(bucket, zero)
        if have != want:
            drift.append(BucketDrift(bucket, have, want))
    return drift


def _repair_aggregates(conn: Conn, account_uuid, drift: list[BucketDrift]) -> None:
    now = utc_now().isoformat()
    to_set: dict[Bucket, Usage] = {}
    audit: dict[Bucket, dict] = {}
    to_retire: list[Bucket] = []
    for item in drift:
        if item.expected.is_zero():
            to_retire.append(item.bucket)
        else:
            to_set[item.bucket] = item.expected
            audit[item.bucket] = {
                "reconciled": {"at": now, "previous": json.loads(json.dumps(item.stored.__dict__))}
            }
    aggregates.soft_delete_buckets(
        conn, account_uuid, to_retire, {"reconciled": {"at": now, "removed": True}}
    )
    aggregates.set_absolute(conn, account_uuid, to_set, audit)
    months = [b.start for b in {*to_set, *to_retire} if b.period is Period.MONTH]
    aggregates.refresh_cap_flags(conn, account_uuid, months)
