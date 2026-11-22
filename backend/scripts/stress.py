"""Load and correctness test against a running stack (stdlib only).

Sends shuffled, duplicated, signed webhook traffic over real HTTP, waits for the workers to drain
the inbox, then checks every account's totals against what was sent, and runs reconcile in dry-run
mode: stored usage must equal usage recomputed from the raw events. Exit code 1 on any mismatch.

    python scripts/stress.py --calls 5000 --concurrency 32
    python scripts/stress.py --calls 5000 --hot        # all traffic on one account
    python scripts/stress.py --calls 20000 --accounts 10 --duplicates 0.3 --late 0.05

Environment (defaults match docker-compose): WEBHOOK_SECRET, ADMIN_API_KEY.
"""

import argparse
import hashlib
import hmac
import http.client
import json
import os
import random
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--calls", type=int, default=2000, help="calls to simulate (2+ events each)")
    p.add_argument("--concurrency", type=int, default=16, help="sender threads")
    p.add_argument("--accounts", type=int, default=10, help="spread over acct_001..acct_NNN")
    p.add_argument("--hot", action="store_true", help="put every call on acct_001")
    p.add_argument("--duplicates", type=float, default=0.2, help="share of events sent 2-3 times")
    p.add_argument("--late", type=float, default=0.05, help="share of calls 35 days old")
    p.add_argument("--drain-timeout", type=float, default=300.0)
    p.add_argument("--seed", type=int, default=None)
    return p.parse_args()


MAX_DELIVERIES = 12


class Client:
    """One keep-alive connection per thread."""

    def __init__(self, base: str, secret: bytes, admin_key: str):
        u = urlparse(base)
        self.host, self.port, self.secret, self.admin_key = (
            u.hostname,
            u.port or 80,
            secret,
            admin_key,
        )
        self.conn = http.client.HTTPConnection(self.host, self.port, timeout=30)

    def _request(self, method, path, body=None, headers=None):
        for attempt in (1, 2):
            try:
                self.conn.request(method, path, body, headers or {})
                r = self.conn.getresponse()
                return r.status, r.read()
            except (http.client.HTTPException, OSError):
                self.conn.close()
                self.conn = http.client.HTTPConnection(self.host, self.port, timeout=30)
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    def webhook(self, payload: dict) -> tuple[int, int]:
        """Deliver like a real provider: 503 and broken connections mean "not stored, send again".
        Returns (final status, redeliveries). The same event_id makes repeats harmless."""
        body = json.dumps(payload).encode()
        headers = {"X-Signature": hmac.new(self.secret, body, hashlib.sha256).hexdigest()}
        for attempt in range(MAX_DELIVERIES):
            try:
                self.conn.request("POST", "/webhooks/calls", body, headers)
                response = self.conn.getresponse()
                response.read()
                status = response.status
            except (http.client.HTTPException, OSError):
                self.conn.close()
                self.conn = http.client.HTTPConnection(self.host, self.port, timeout=30)
                status = 0
            if status not in (0, 502, 503, 504):
                return status, attempt
            time.sleep(min(0.1 * 2**attempt, 3) * (0.5 + random.random() / 2))
        return status, MAX_DELIVERIES

    def admin(self, method: str, path: str):
        """The runner uses only GETs and a dry-run reconcile, which are safe to repeat."""
        for delay in (0.25, 0.5, 1, 0):
            try:
                status, data = self._request(
                    method, path, None, {"Authorization": f"Bearer {self.admin_key}"}
                )
            except (http.client.HTTPException, OSError):
                status = 0
            if status == 200:
                return status, json.loads(data)
            if status not in (0, 429, 502, 503, 504) or not delay:
                return status, None
            time.sleep(delay)


def build_traffic(args, run: str, rng: random.Random):
    """Returns (events, expected) where expected[account] = (completed calls, seconds, cents)."""
    now = datetime.now(UTC)
    events, expected = [], {}
    for i in range(args.calls):
        account = "acct_001" if args.hot else f"acct_{rng.randint(1, args.accounts):03d}"
        call, seconds = f"{run}_c{i}", rng.randint(30, 1800)
        cost = max(seconds // 30, 1)
        ended = now - timedelta(days=35) if rng.random() < args.late else now
        started = ended - timedelta(seconds=seconds)

        def ev(kind, when, dur=0, cst=0, tag="", *, i=i, account=account, call=call):
            return {
                "event_id": f"{run}_{tag}{i}",
                "event_type": kind,
                "account_id": account,
                "call_id": call,
                "timestamp": when.isoformat(),
                "duration_seconds": dur,
                "cost_cents": cst,
                "destination_country": "US",
            }

        events += [
            ev("call.started", started, tag="s"),
            ev("call.ended", ended, seconds, cost, "e"),
        ]
        c, s, m = expected.get(account, (0, 0, 0))
        expected[account] = (c + 1, s + seconds, m + cost)
    resend = [e for e in events if rng.random() < args.duplicates for _ in range(rng.randint(1, 2))]
    events += resend
    rng.shuffle(events)
    return events, expected, len(resend)


def percentile(sorted_values, q):
    return sorted_values[min(int(len(sorted_values) * q), len(sorted_values) - 1)]


def main() -> int:
    args = parse_args()
    seed = args.seed if args.seed is not None else random.randrange(10**6)
    rng, run = random.Random(seed), f"st{uuid.uuid4().hex[:8]}"
    secret = os.environ.get("WEBHOOK_SECRET", "callzo_test_secret_change_me").encode()
    admin_key = os.environ.get("ADMIN_API_KEY", "dev-only-admin-key-change-me")
    main_client = Client(args.url, secret, admin_key)

    status, _ = main_client.admin("GET", "/admin/v1/overview")
    if status != 200:
        print(f"cannot reach the admin API (HTTP {status}); check --url and ADMIN_API_KEY")
        return 2

    accounts = sorted(
        {"acct_001"} if args.hot else {f"acct_{n:03d}" for n in range(1, args.accounts + 1)}
    )
    before = {}
    for a in accounts:
        s, usage = main_client.admin("GET", f"/v1/accounts/{a}/usage")
        if s != 200:
            print(f"{a}: HTTP {s} (does it exist?)")
            return 2
        u = usage["lifetime"]
        before[a] = (u["completed_calls"], u["duration_seconds"], u["cost_cents"])

    events, expected, resent = build_traffic(args, run, rng)
    print(
        f"run {run} seed {seed}: {args.calls} calls -> {len(events)} deliveries "
        f"({resent} duplicates) on {len(accounts)} account(s), {args.concurrency} senders"
    )

    latencies, codes, errors, redelivered = [], {}, [], [0]
    lock, cursor = threading.Lock(), [0]

    def sender():
        client = Client(args.url, secret, admin_key)
        while True:
            with lock:
                i = cursor[0]
                cursor[0] += 1
            if i >= len(events):
                return
            t0 = time.perf_counter()
            try:
                code, again = client.webhook(events[i])
            except Exception as exc:
                with lock:
                    errors.append(repr(exc))
                continue
            dt = time.perf_counter() - t0
            with lock:
                latencies.append(dt)
                redelivered[0] += again
                codes[code] = codes.get(code, 0) + 1

    start = time.perf_counter()
    threads = [threading.Thread(target=sender) for _ in range(args.concurrency)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ingest_seconds = time.perf_counter() - start

    lat = sorted(latencies)
    print(
        f"\nINGEST   {len(lat) / ingest_seconds:8.0f} req/s   p50 {percentile(lat, 0.5) * 1000:6.1f} ms   "
        f"p95 {percentile(lat, 0.95) * 1000:6.1f} ms   p99 {percentile(lat, 0.99) * 1000:6.1f} ms   "
        f"max {lat[-1] * 1000:6.1f} ms"
    )
    print(
        f"         status codes {dict(sorted(codes.items()))}   redelivered {redelivered[0]}   transport errors {len(errors)}"
    )

    deadline = time.perf_counter() + args.drain_timeout
    overview = None
    last_status = None
    drained = False
    while time.perf_counter() < deadline:
        last_status, overview = main_client.admin("GET", "/admin/v1/overview")
        if last_status == 200 and overview["inbox"]["pending"] == 0:
            drained = True
            break
        time.sleep(0.25)
    total_seconds = time.perf_counter() - start
    unique = len(events) - resent
    drain_result = "inbox empty" if drained else "timed out"
    print(
        f"DRAIN    {drain_result} {total_seconds - ingest_seconds:6.1f} s after the last send; "
        f"end to end {unique / total_seconds:.0f} unique events/s"
    )

    failures = []
    ok_codes = {200, 202}
    bad = {c: n for c, n in codes.items() if c not in ok_codes}
    if bad or errors:
        failures.append(f"unexpected responses {bad}, transport errors {len(errors)}")
    if not drained:
        detail = overview["inbox"] if overview is not None else f"overview status {last_status}"
        failures.append(f"inbox did not drain: {detail}")
    elif overview["inbox"]["dead"]:
        failures.append(f"inbox not clean: {overview['inbox']}")

    print("\nTOTALS   account    expected(calls, sec, cents)        actual")
    for a in accounts:
        status, usage = main_client.admin("GET", f"/v1/accounts/{a}/usage")
        if status != 200:
            failures.append(f"{a}: usage verification returned status {status}")
            continue
        u = usage["lifetime"]
        got = (
            u["completed_calls"] - before[a][0],
            u["duration_seconds"] - before[a][1],
            u["cost_cents"] - before[a][2],
        )
        want = expected.get(a, (0, 0, 0))
        mark = "ok" if got == want else "MISMATCH"
        print(f"         {a}  {want!s:34} {got!s:28} {mark}")
        if got != want:
            failures.append(f"{a}: expected {want}, got {got}")

    print("\nRECONCILE (dry run: stored usage vs usage recomputed from raw events)")
    for a in accounts:
        t0 = time.perf_counter()
        s, report = main_client.admin("POST", f"/admin/v1/accounts/{a}/reconcile?dry_run=true")
        took = time.perf_counter() - t0
        drift = len(report["drift"]) if s == 200 else -1
        print(
            f"         {a}  {report['calls_seen'] if s == 200 else '?':>6} calls replayed in "
            f"{took:5.2f} s   drift buckets: {drift}"
        )
        if s != 200 or drift:
            failures.append(f"{a}: reconcile status {s}, drift {drift}")

    print("\nRESULT   " + ("PASS" if not failures else "FAIL"))
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
