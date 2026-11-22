-- CONVENTIONS (every table, no exceptions)
--   id          uuid        surrogate primary key (gen_random_uuid())
--   created_at  timestamptz set once; the trigger below makes it immutable
--   updated_at  timestamptz maintained by the trigger below, never by application code
--   deleted_at  timestamptz soft delete: NULL = live. Reads filter on it; unique indexes that
--                           must hold only for live rows are partial (WHERE deleted_at IS NULL)
--   metadata    jsonb       free-form object for audit trails and operator labels (max 16 KB)
-- Provider/natural identifiers are ordinary columns with their own unique indexes.
--
-- Every hot query is an index lookup or an index range scan.
-- tests/integration/test_query_plans.py fails if one falls back to a sequential scan.

CREATE FUNCTION touch_row() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.created_at := OLD.created_at;
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- ----------------------------------------------------------------------------------------
CREATE TABLE accounts (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id         text NOT NULL CHECK (external_id ~ '^[A-Za-z0-9_.:-]{1,128}$'),
  monthly_cap_minutes integer NOT NULL CHECK (monthly_cap_minutes >= 0),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  deleted_at          timestamptz,
  metadata            jsonb NOT NULL DEFAULT '{}'
                        CONSTRAINT accounts_metadata_ok CHECK (jsonb_typeof(metadata) = 'object' AND pg_column_size(metadata) <= 16384),
  -- Full (not partial) on purpose: a deleted account keeps its external_id, so events for it
  -- can never be attributed to a different account. Bring it back with restore.
  CONSTRAINT accounts_external_id_key UNIQUE (external_id)
);
-- Listing deleted accounts in the console.
CREATE INDEX accounts_deleted ON accounts (external_id) WHERE deleted_at IS NOT NULL;
CREATE TRIGGER accounts_touch BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION touch_row();

-- ----------------------------------------------------------------------------------------
-- Immutable fact log plus delivery state. No foreign key on purpose: an event for an account
-- that is not provisioned yet is kept and retried, never refused.
-- deleted_at means "voided": excluded from metering and reconcile, but the row (and its
-- provider_event_id) stays, so a redelivery of a voided event is still recognised as a duplicate.
CREATE TABLE call_events (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_event_id   text NOT NULL,                 -- the provider's event_id: idempotency key
  account_external_id text NOT NULL,
  provider_call_id    text NOT NULL,
  event_type          text NOT NULL CHECK (event_type IN ('call.started', 'call.ended', 'call.failed')),
  occurred_at         timestamptz NOT NULL,          -- when it happened (provider clock)
  received_at         timestamptz NOT NULL DEFAULT now(),  -- when we got it; drives the late flag
  duration_seconds    integer NOT NULL CHECK (duration_seconds >= 0),
  cost_cents          bigint NOT NULL CHECK (cost_cents >= 0),
  destination_country text NOT NULL,
  raw_body            bytea NOT NULL,                -- exact bytes that were signed
  status              text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processed', 'dead')),
  attempts            integer NOT NULL DEFAULT 0,
  next_attempt_at     timestamptz NOT NULL DEFAULT now(),
  last_error          text,
  processed_at        timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  deleted_at          timestamptz,
  metadata            jsonb NOT NULL DEFAULT '{}'
                        CONSTRAINT call_events_metadata_ok CHECK (jsonb_typeof(metadata) = 'object' AND pg_column_size(metadata) <= 16384),
  CONSTRAINT call_events_provider_event_id_key UNIQUE (provider_event_id)
);
-- All live events of one call (worker) and of one account in call order (reconcile).
CREATE INDEX call_events_by_call ON call_events (account_external_id, provider_call_id) WHERE deleted_at IS NULL;
-- The claim query. Only unfinished live rows are indexed, so it stays tiny however large the log gets.
CREATE INDEX call_events_due ON call_events (next_attempt_at) WHERE status = 'pending' AND deleted_at IS NULL;
-- Console: newest first, per status / per account / voided.
CREATE INDEX call_events_by_status ON call_events (status, received_at DESC, id DESC) WHERE deleted_at IS NULL;
CREATE INDEX call_events_by_account ON call_events (account_external_id, received_at DESC, id DESC) WHERE deleted_at IS NULL;
CREATE INDEX call_events_voided ON call_events (received_at DESC, id DESC) WHERE deleted_at IS NOT NULL;
CREATE TRIGGER call_events_touch BEFORE UPDATE ON call_events FOR EACH ROW EXECUTE FUNCTION touch_row();

-- ----------------------------------------------------------------------------------------
-- Current resolved state of each call. Doubles as the ledger of what a call has already
-- contributed to usage_aggregate, so a change is applied as (new - old), exactly once.
CREATE TABLE calls (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id        uuid NOT NULL REFERENCES accounts (id),
  provider_call_id  text NOT NULL,
  status            text NOT NULL DEFAULT 'in_progress'
                      CHECK (status IN ('in_progress', 'completed', 'failed')),
  started_at        timestamptz,
  ended_at          timestamptz,
  duration_seconds  integer NOT NULL DEFAULT 0 CHECK (duration_seconds >= 0),
  cost_cents        bigint NOT NULL DEFAULT 0 CHECK (cost_cents >= 0),
  usage_date        date,                              -- UTC day of the terminal event
  is_late           boolean NOT NULL DEFAULT false,
  terminal_event_id uuid REFERENCES call_events (id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  deleted_at        timestamptz,
  metadata          jsonb NOT NULL DEFAULT '{}'
                      CONSTRAINT calls_metadata_ok CHECK (jsonb_typeof(metadata) = 'object' AND pg_column_size(metadata) <= 16384),
  CHECK ((status = 'in_progress') = (usage_date IS NULL))
);
CREATE UNIQUE INDEX calls_live_key ON calls (account_id, provider_call_id) WHERE deleted_at IS NULL;
CREATE INDEX calls_terminal_event ON calls (terminal_event_id) WHERE terminal_event_id IS NOT NULL;
-- "Finished calls of an account, newest first": the evidence behind a total.
CREATE INDEX calls_recent ON calls (account_id, ended_at DESC, id DESC)
  WHERE deleted_at IS NULL AND ended_at IS NOT NULL;
CREATE TRIGGER calls_touch BEFORE UPDATE ON calls FOR EACH ROW EXECUTE FUNCTION touch_row();

-- ----------------------------------------------------------------------------------------
-- Additive rollups. One live row per (account, period granularity, period start).
-- A call outcome touches exactly 4 rows (day, week, month, lifetime): O(1) write.
-- Any standard period is one index lookup: O(1). Custom ranges read a handful of buckets.
CREATE TABLE usage_aggregate (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id       uuid NOT NULL REFERENCES accounts (id),
  period_type      text NOT NULL CHECK (period_type IN ('day', 'week', 'month', 'lifetime')),
  period_start     date NOT NULL,
  completed_calls  bigint NOT NULL DEFAULT 0,
  failed_calls     bigint NOT NULL DEFAULT 0,
  duration_seconds bigint NOT NULL DEFAULT 0,
  cost_cents       bigint NOT NULL DEFAULT 0,
  late_calls       bigint NOT NULL DEFAULT 0,
  late_cost_cents  bigint NOT NULL DEFAULT 0,
  cap_reached_at   timestamptz,                        -- month rows only
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  deleted_at       timestamptz,
  metadata         jsonb NOT NULL DEFAULT '{}'
                     CONSTRAINT usage_aggregate_metadata_ok CHECK (jsonb_typeof(metadata) = 'object' AND pg_column_size(metadata) <= 16384),
  CONSTRAINT period_start_aligned CHECK (
    CASE period_type
      WHEN 'day'   THEN true
      WHEN 'week'  THEN extract(isodow FROM period_start) = 1
      WHEN 'month' THEN extract(day FROM period_start) = 1
      ELSE period_start = DATE '1970-01-01'
    END),
  CONSTRAINT cap_only_on_month CHECK (cap_reached_at IS NULL OR period_type = 'month')
);
CREATE UNIQUE INDEX usage_aggregate_live_key
  ON usage_aggregate (account_id, period_type, period_start) WHERE deleted_at IS NULL;
CREATE TRIGGER usage_aggregate_touch BEFORE UPDATE ON usage_aggregate
  FOR EACH ROW EXECUTE FUNCTION touch_row();

-- Totals must never go negative. This is a trigger, not CHECK constraints, because a CHECK is
-- evaluated on the row *proposed* for insertion, and our upserts propose signed deltas
-- (e.g. -1 failed call when a failure is corrected to a completion). An AFTER trigger sees
-- the final row, whichever way the upsert resolved, and aborts the transaction if it is wrong.
CREATE FUNCTION usage_aggregate_assert_non_negative() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.completed_calls < 0 OR NEW.failed_calls < 0 OR NEW.duration_seconds < 0
     OR NEW.cost_cents < 0 OR NEW.late_calls < 0 OR NEW.late_cost_cents < 0 THEN
    RAISE EXCEPTION 'usage_aggregate % % % would go negative',
      NEW.account_id, NEW.period_type, NEW.period_start USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END $$;

CREATE TRIGGER usage_aggregate_non_negative
  AFTER INSERT OR UPDATE ON usage_aggregate
  FOR EACH ROW EXECUTE FUNCTION usage_aggregate_assert_non_negative();

-- ----------------------------------------------------------------------------------------
-- Created by the migration runner before this file runs; brought under the same conventions here.
CREATE TRIGGER schema_migrations_touch BEFORE UPDATE ON schema_migrations
  FOR EACH ROW EXECUTE FUNCTION touch_row();
