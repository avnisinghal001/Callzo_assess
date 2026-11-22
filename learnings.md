# Build and verification notes

Every measurement behind the READMEs, including the runs that failed. The problems and their fixes are in [the root README](README.md#problems-we-hit), [backend](backend/README.md#problems-we-hit) and [frontend](frontend/README.md#problems-we-hit).

All numbers come from one Apple-silicon laptop with one Postgres. Workloads and settings changed between runs, so each row describes itself and should not be compared with its neighbours.

## Load and recovery

| Run | Result |
|---|---|
| Hot account, 8,000 calls on one account, outside Docker, while `NOTIFY` was still in use | Exact totals. 2,045 deliveries/s, 966 events/s counted end to end, 43 ms p95 |
| Hot account with 120 reconcile requests at once, 6,000 calls | Exact totals, no deadlocks. Counting fell to 197 events/s, because repair and counting share the account lock |
| **One** API server, 12,000 calls, 48 senders, worker interrupted | **Failed.** 8 deliveries ended in `503`, three accounts were a call short. Accepted work was all counted; rejected work needed the sender to try again |
| Inserts alone, 32 clients, with and without `NOTIFY` in the same commit | 3,755 to 4,197/s without, 1,357 to 1,921/s with |
| Two API servers, four workers, 8,000 calls, ten accounts | Exact totals, no drift. 20,893 deliveries, 401/s, 274 ms p95 |
| Same, killing ten worker processes, one API process, and Postgres itself | Exact totals, no drift, after 325 redeliveries. 296 deliveries/s, 407 ms p95 |
| Clean checkout, 1,000 calls, 16 senders | Exact totals. 2,598 deliveries, 2,582/s, 9.9 ms p95 |
| Clean checkout, 3,000 calls, both workers killed three times | Exact totals. The queue emptied 61 s after the last send, which is the 60 s lease |
| Clean checkout, 8,000 calls, one of two API servers killed mid-send | Exact totals. No error reached the sender. Five events that were stored but never answered came back as `200` |
| Five API kills in turn, 10,550 requests (1,397 page loads, 9,153 webhooks), after the gateway fix | No errors. Slowest answer 0.68 s |

## The bug the load runs missed

None of the runs above lasted long enough to meet the hourly reconcile check, which first fires five minutes after startup. When it did, the worker that ran it left a transaction open and stopped committing. The other workers carried on, so totals stayed right and every check passed. With a single worker, counting would have stopped.

It was found by reading a screenshot: the console said one worker was awake, and Docker said two were healthy. `pg_stat_activity` showed a connection idle in a transaction for nine minutes.

Three things let it through, and each has its own fix:

1. The job's read did not close its transaction. Now it does.
2. The worker's connection allowed it. Now it cannot hold a transaction open by accident.
3. The health check passed before the heartbeat was committed. Now it passes after.

The existing test ran the job and checked the result on **one** connection, which can always see its own uncommitted work. The new tests check from a second connection. After the fix, forcing the check four times in a row left both workers counting and no transaction open.

## Checks on the final code

- **Backend:** 570 tests on Postgres 17. Lint and format clean.
- **Callzo's simulator:** each scenario run alone against empty tables, and all together from a clean checkout. An independent SQL recount matched all ten accounts on all six counters.
- **Console:** eight of eight scenarios in Chrome, also with one API server killed. No console errors, and no sideways scrolling at 375px.
- **Frontend:** 15 unit tests, type check, production build, and 53 of 53 checks in Chrome against the Docker image. Keyboard zoom of the chart was checked separately.
- **Images:** the frontend builds for x86 and ARM, and so does the backend.

## What this does not prove

Database failover, a restore from backup, weeks of growth, x86 hardware, and use with a screen reader. A hard cap also needs a reservation in the dialer, because this service hears about calls after they happen.
