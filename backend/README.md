<img src="docs/hero.png" alt="The metering console on desktop and phone, with every scenario passing">

# Task 1: Usage metering service

Takes signed call events from a phone provider, stores each one once, keeps exact usage for every account, watches the monthly cap, and serves it all through an authenticated API.

Python 3.13, FastAPI, PostgreSQL 17, plain SQL with psycopg, nginx.

[Run it](#run-it) · [Architecture](#architecture) · [Each scenario, in the database](#each-scenario-in-the-database) · [Decisions](#decisions-and-what-they-cost) · [The cap](#the-monthly-cap) · [Data model](#data-model) · [When things break](#when-things-break) · [API](#api) · [Tests](#tests-and-evidence) · [Problems](#problems-we-hit) · [Next](#what-comes-next)

## Run it

From this folder, with Docker running:

```bash
docker compose up
```

The app image is published as [`avnisinghal01/callzo-task1-backend:1.0.1`](https://hub.docker.com/r/avnisinghal01/callzo-task1-backend), for x86 and ARM. To build it from this folder instead, see below.

Compose starts Postgres, the migrations, two API servers, two workers and nginx. Callzo's simulator then sends every scenario once and exits. Open the console at [localhost:8000](http://localhost:8000). No `.env` is needed; [`.env.example`](.env.example) lists what can be changed.

```bash
# Ask for an account's usage
curl -H 'Authorization: Bearer dev-only-api-key-change-me' localhost:8000/v1/accounts/acct_001/usage

# Run the tests (--build matters: without it Docker reuses an old image)
docker compose --profile test run --rm --build tests

# Build from this folder instead of pulling
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build

# Run one simulator scenario
docker compose run --rm simulator --url http://gateway:8080/webhooks/calls --scenario duplicates

# See what it did to the database, ending with an independent recount
docker compose exec -T postgres psql -X -U callzo -d callzo < scripts/scenarios.sql

# Compare every total with the raw events, changing nothing
docker compose exec api python -m app.cli reconcile --dry-run

# Stop. Add -v to also erase the database
docker compose down
```

## Architecture

<img src="docs/architecture.png" alt="Prove it, store it, claim it, resolve the call, add the difference. Under each step: what happens when it breaks">

The API does as little as possible: prove, validate, store, answer. Workers do the rest, so the first attempt and the tenth retry run the same code. For where each part runs, see the [system diagram](../docs/architecture.png).

**The one idea that matters.** A worker never "adds an event". It reads all of a call's events, decides what that call should count for, subtracts what it already counted for, and adds only the difference. Run it twice and the second difference is zero. That single rule covers duplicates, wrong order, corrections, retries and crashes.

## The console

| | |
|---|---|
| <img src="docs/simulator.png" alt="A duplicate scenario with sent, checked, stored and counted"> | <img src="docs/accounts.png" alt="Accounts against their caps"> |
| <img src="docs/live.png" alt="Traffic, queue, servers and workers"> | <img src="docs/events.png" alt="One event, from arrival to counted"> |

**Simulator** runs eight scenarios through the service's own checks, storage and workers, then compares the result with an expected total worked out separately. **Live** shows traffic and every server. **Accounts** sets caps. **Events** can retry, set aside or restore any event. **History** records who did what.

## Each scenario, in the database

You said you will ask what happened in the database. Callzo's simulator was run one scenario at a time against empty tables. Call lengths are random, so seconds and cents differ per run; the shape does not.

| Scenario | Answers | `call_events` | `calls` | `usage_aggregate` |
|---|---|---|---|---|
| `normal` | 40 × `202` | 40 processed | 20 completed | November: 20 calls, 8,844 s, 296 cents |
| `duplicates` | 10 × `202`, 13 × `200` | **10**, not 23 | 10 completed | November: 10 calls, 1,532 s, 51 cents |
| `out_of_order` | 20 × `202` | 20 processed | 10 completed, start time filled in later | November: 10 calls, 1,292 s, 43 cents |
| `late` | 8 × `202` | 8 processed | 8 completed, flagged late | **October**: 8 calls, 8 late. November untouched |
| `malformed` | 2 × `400`, 3 × `422` | 0 | 0 | 0 |
| `bad_signature` | 6 × `401` | 0 | 0 | 0 |
| `cap_burst` | 80 × `202` | 80 processed | 40 completed | 24,000 s against a cap of 12,000 s. Crossed on call 20, all 40 recorded |

A new event answers `202` (stored, not yet counted). A copy answers `200`. Counting usually follows within a fraction of a second.

## Decisions and what they cost

| Decision | Why | What it costs |
|---|---|---|
| **Store first, count later** | A slow or broken count can never lose an event | Totals trail by a moment. The cap sees processed events only |
| **Postgres is the queue** | One system to run, and the event and its state commit together | Less throughput than a real queue |
| **Add the difference, not the event** | One formula for new, repeated, corrected and moved calls | Each call row must remember what it contributed |
| **Four ready-made totals** (day, week, month, lifetime) | Reads and the cap check are one index lookup, however long the history | Each call updates four rows. A very busy account's workers queue briefly |
| **One event per transaction** | Claiming ten deadlocked | More round trips |
| **A fixed lock order**: account (shared), call, totals (sorted) | Two workers can never wait on each other in a circle | Reconcile repair pauses that account's counting |
| **Claims are leases** | A worker can die at any line | A dead worker's event waits up to 60 s |
| **Plain SQL, no ORM** | The locking and upserts *are* the design, so they should be visible | More SQL to read |
| **Poll every 0.2 s, no `NOTIFY`** | Notifications made inserts 2 to 3 times slower | Up to 0.2 s of idle delay |
| **Keep the exact signed bytes** | Evidence, and a replay needs nothing else | Storage |

### How totals are kept

Each account has additive rows for completed calls, failed calls, seconds, cents, late calls and late cents. A new call touches exactly four. A correction that moves a call to another date touches at most seven. Neither number grows with history.

A custom range is covered with the biggest whole blocks that fit. **30 January to 8 March 2026** is two days, February, 1 March, and the week from 2 March: five rows for 38 days, no overlaps. The code is a pure function in [`buckets.py`](app/modules/aggregates/buckets.py).

## The monthly cap

**The cap is soft.** This service hears about a call after it happened, so refusing the event would only lose a billing fact. It records everything and answers one question for the dialer: `new_calls_allowed`.

| Used this month | `status` | `new_calls_allowed` |
|---|---|---|
| under 80% | `ok` | `true` |
| 80% up to one second below | `warning` | `true` |
| **exactly at the cap** | `reached` | **`false`** |
| one second over, or more | `exceeded` | `false` |

- Compared in whole seconds. No floats, no rounding.
- The call that crosses the line is counted in full. Calls already running, and reports still on the way, can overshoot.
- The default is 200 minutes, changeable per account. A cap of 0 blocks everything.
- `reached_at` records the moment of crossing. It clears if a correction takes the account back under.
- A late call counts in the month it happened. It cannot use up this month's cap.

## Data model

```mermaid
erDiagram
    ACCOUNTS ||--o{ CALLS : owns
    ACCOUNTS ||--o{ USAGE_AGGREGATE : "has totals"
    CALL_EVENTS |o--o{ CALLS : "decides the end of"
    ACCOUNTS {
        uuid id PK
        text external_id UK "acct_001"
        int monthly_cap_minutes
    }
    CALL_EVENTS {
        uuid id PK
        text provider_event_id UK "stops duplicates"
        text account_external_id "no foreign key"
        text provider_call_id
        timestamptz occurred_at
        timestamptz received_at
        int duration_seconds
        bigint cost_cents
        bytea raw_body "exact signed bytes"
        text status "pending, processed, dead"
        timestamptz next_attempt_at
    }
    CALLS {
        uuid id PK
        uuid account_id FK
        uuid terminal_event_id FK
        text provider_call_id
        text status
        date usage_date "UTC"
        boolean is_late
    }
    USAGE_AGGREGATE {
        uuid id PK
        uuid account_id FK
        text period_type "day, week, month, lifetime"
        date period_start
        bigint duration_seconds
        bigint cost_cents
        timestamptz cap_reached_at
    }
```

| Table | Why it exists |
|---|---|
| `accounts` | The cap, and the link from your account ID to ours. A removed account keeps its ID, so its events can never land on someone else |
| `call_events` | The truth. Inbox, retry state and permanent log in one. **No foreign key on purpose:** an event for an account that does not exist *yet* is kept and retried |
| `calls` | What each call contributed so far. The key is account **and** call ID, so one account can never change another's call |
| `usage_aggregate` | The answer, ready to read. Can always be rebuilt from `call_events` |
| `audit_log`, `webhook_stats`, `service_instances`, `scheduled_jobs`, `schema_migrations` | Running the service: changes, traffic, heartbeats, jobs, applied migrations |

Every table has a UUID key, `created_at`, `updated_at`, `deleted_at` and a `metadata` JSON column. A trigger keeps the times honest. Request-path queries use an index, and [a test](tests/integration/test_query_plans.py) fails if one falls back to scanning a table. Reconciliation reads one account's whole history on purpose, through an index.

## When things break

| What breaks | What happens |
|---|---|
| Forged or missing signature | `401`, before the body is parsed. Nothing stored |
| Broken JSON, empty body | `400` |
| Missing field, wrong type, unknown event type | `422`, naming the fields but never echoing the input |
| Over 64 KB | `413` |
| Same event ID, different content | `409`. The first stands, and it is logged as an error |
| Database down, or every connection busy | `503` with `Retry-After`. The provider sends again, safely |
| API dies after storing, before answering | The resend finds the row and gets `200` |
| One API server dies | nginx hands the event to the other, and tries once more if the list of servers changes mid-request. Only for reads and webhooks, which are safe to repeat |
| A worker is stuck but running | Its health check needs a committed heartbeat, so it turns unhealthy, and the console shows it as silent |
| Worker dies mid-event | Its work rolls back. Another takes over after the 60 s lease |
| An event that kills every worker | Attempts are counted *when claimed*, so after 8 it is set aside. It cannot loop |
| Unknown account, or any processing error | Retried after 1–2 s, 2–4 s, 4–8 s … up to 5 min. After 8 tries it is `dead`: visible, and retryable with `python -m app.cli retry-dead` |
| All workers stop | Events keep being accepted. Queue size and oldest wait are shown |
| A total is wrong | The hourly check reports it. `python -m app.cli reconcile` repairs it in place and leaves a note |
| Reconcile runs during traffic | A check does not block. A repair takes that account's lock, so nothing is counted twice |

## API

| Endpoint | Needs | Gives |
|---|---|---|
| `POST /webhooks/calls` | `X-Signature` | `202`, `200`, or a clear 4xx |
| `GET /v1/accounts/{id}/usage` | read key | Today, week, month, lifetime, and the cap |
| `GET /v1/accounts/{id}/usage/series` | read key | Daily, weekly or monthly rows |
| `GET /v1/accounts/{id}/usage/range` | read key | One exact total for any dates, up to ten years |
| `GET /v1/accounts/{id}/usage/calls` | read key | The calls behind the number, newest first |
| `/admin/v1/…` | admin key | Accounts, events, reconcile, history, fleet, sandbox |
| `GET /health/live`, `/health/ready` | nothing | Is the process up? Can it reach Postgres? |
| `GET /metrics` | inside the network | Prometheus: requests, queue, connection pool |

**Keys.** `Authorization: Bearer …`. A missing or wrong key is `401`; a read key on an admin route is `403`. All compared in constant time. Every secret comes from the environment, and the app will not start without them. The compose file holds development values only, including the webhook secret printed in your spec. To rotate, set the new value and keep the old one in `*_PREVIOUS` until clients switch.

**The console** opens without a password, because it is published on `127.0.0.1` only, unknown hosts are refused, and its cookie cannot be used from another site. For anything shared, set `CONSOLE_OPEN_ACCESS=false` and `ENABLE_SANDBOX=false`, and put it behind your sign-in and TLS.

**Logs** are JSON. `X-Request-ID` ties a request to its log lines and its history entry.

## Running more than one

API servers and workers share nothing but Postgres, so you add more and they coordinate:

```bash
docker compose up -d --scale api=3 --scale worker=6
```

Connections needed = API servers × 8 + workers, kept under Postgres's limit (200 here). Each server holds 2 to 8 connections and lets 32 requests wait up to 5 s, then answers `503` rather than hanging. Watch `db_requests_waiting` before adding more. An hourly job is claimed with one `UPDATE`, so exactly one worker runs it and there is no leader to lose.

## Tests and evidence

570 tests, unit and integration, against a real Postgres. The ones worth opening:

| Test | Proves |
|---|---|
| [`test_metering.py`](tests/integration/test_metering.py) | Any order, any number of copies, same totals. The cap at its exact boundary |
| [`test_concurrency.py`](tests/integration/test_concurrency.py) | Many workers on one account: exact totals, no deadlock |
| [`test_worker_crash.py`](tests/integration/test_worker_crash.py) | A worker can die after claiming. A poison event ends |
| [`test_operations.py`](tests/integration/test_operations.py) | A worker still commits after a scheduled job. One job, one worker. Key rotation |
| [`test_reconcile.py`](tests/integration/test_reconcile.py) | Corrupted totals are found and rebuilt |
| [`test_query_plans.py`](tests/integration/test_query_plans.py) | Every hot query uses its index |

| Load run, one laptop | Result |
|---|---|
| 1,000 calls, 2,598 deliveries | Exact. 2,582 deliveries/s, 9.9 ms p95 |
| 3,000 calls, both workers killed three times | Exact. The queue emptied 61 s after the last send: the lease |
| 8,000 calls, one of two API servers killed mid-send | Exact. No error reached the sender. Five events whose reply was lost came back as `200` |
| 10,550 requests while an API server was killed five times | No errors |
| 12,000 calls, **one** API server, worker killed | **Failed.** 8 deliveries ended in `503`, three accounts a call short. This is why there are two servers |

Workloads differ, so do not compare rows. More in [learnings.md](../learnings.md). Repeat one with `python3 scripts/stress.py --calls 1000 --concurrency 16 --seed 42`.

## Problems we hit

| Problem | Cause | Fix |
|---|---|---|
| A worker went silent after the hourly check, and still looked healthy | Reading the last, empty page of accounts opened a transaction nothing closed. Later commits were only savepoints, `now()` stood still, and new events looked "not due yet" | The read closes its own transaction, the worker connection cannot hold one open, and "healthy" comes after a real commit. Two new tests fail with the old code |
| Killing a server gave a browser `504` | Docker removed it from DNS while nginx was mid-retry, and nginx stops when its list changes | One fresh try, only where repeating is harmless |
| A prototype deadlocked 47 times in one run | Workers claimed ten events and locked rows in different orders | Claim one, and one fixed lock order |
| Corrections retried forever | `CHECK` runs on the proposed row, and a correction proposes −1 | A trigger that checks the final row |
| The lock test passed without the lock | The second worker was waiting on an uncommitted insert instead | Commit the row first. Now it fails without the lock |
| Inserts slowed to 1,400–1,900/s from about 4,000 | `NOTIFY` takes a database-wide lock at commit | Removed it. Workers poll a tiny index |
| Overload lost deliveries | One API server, and a sender that gave up | Two servers, nginx retry, bounded queue, sender that resends |
| A full connection pool did not refuse anyone | In psycopg, `max_waiting=0` means *unlimited* | A real limit of 32, with a test |
| The cap never tripped | The default of 500 minutes is above what the simulator sends | 200, so the burst crosses it |
| A resend with a changed country got `200` | That field was missing from the comparison | Compare it too: `409` |
| Log lines broke | `event` is a reserved word in the logger | Renamed to `event_id` |
| "All tests pass", but the old ones | Docker reused a stale test image | `--build` in the documented command |
| Index tests failed on good queries | Postgres rightly scans tiny tables | Fill the tables with realistic rows first |
| The proof query reported false errors | It joined day rows to lifetime totals | Filter both sides, compare all six counters |

**Do the tests have teeth?** These were broken on purpose, one at a time, and a test failed every time: the per-call lock, the reconcile transaction, cross-site protection, session expiry, the console's off switch, the job claim, reconcile's lock-free check, shared traffic counters, secret rotation, and the cap flag after a cap change.

## If you change the requirement

| You ask for | What changes |
|---|---|
| A hard cap | A reservation call before dialling. Counting stays as it is |
| A cap on money | Compare `cost_cents` with a new column |
| Late events go to review | A status on `calls`, left out of the difference |
| Customer time zones | A zone on `accounts`, used where `usage_date` is set, then reconcile |
| Alert at the cap | An outbox row in the same commit, and a sender |
| A new event type | The allowed list, `resolve_call`, one test |
| A hundred times the traffic | More workers, partition `call_events` by month, split hot totals into shards |

## What comes next

1. **Closed months.** Past totals can still change today. Invoices need a closed period and adjustments.
2. **Per-customer keys** with scopes, instead of one read key.
3. **Retention.** The log grows forever, and reconcile reads all of an account's share.
4. **Production Postgres:** a standby, backups, and a restore someone has practised.
5. **Alerts** on queue age, dead events and drift. The numbers exist; nothing pages anyone.
6. **Operator identity** through single sign-on. History records which key acted, not which person.

The console, audit log and fleet view go beyond the brief. They were built to make the walkthrough visible, and none of them decides what gets counted.

## Code map

```text
app/core/               settings, database, security, logging, metrics
app/modules/webhooks/   prove, validate, store
app/modules/inbox/      the queue: claim, retry, set aside
app/modules/metering/   decide the call, add the difference, the worker
app/modules/aggregates/ totals and date maths, as pure functions
app/modules/usage/      the read API and the cap
app/modules/reconcile/  rebuild from raw events
app/modules/…           accounts, audit, fleet, jobs, health, ops
app/console/            the console, with no build step
gateway/  migrations/  scripts/  tests/
```

In each module: `router.py` speaks HTTP, `service.py` holds rules and transactions, `repository.py` holds the SQL.
