-- Operating the service on many servers. Same conventions as 001 for every table.

-- Who changed what. Written in the same transaction as the change, so neither exists alone.
CREATE TABLE audit_log (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  action     text NOT NULL,                  -- e.g. account.update, event.void
  target     text NOT NULL,                  -- e.g. acct_001, an event uuid
  actor      text NOT NULL,                  -- key fingerprint, or "scheduler"; never a secret
  request_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  metadata   jsonb NOT NULL DEFAULT '{}'     -- the change itself
               CONSTRAINT audit_log_metadata_ok CHECK (jsonb_typeof(metadata) = 'object' AND pg_column_size(metadata) <= 16384)
);
CREATE INDEX audit_log_recent ON audit_log (created_at DESC, id DESC) WHERE deleted_at IS NULL;
CREATE INDEX audit_log_by_target ON audit_log (target, created_at DESC, id DESC) WHERE deleted_at IS NULL;
CREATE TRIGGER audit_log_touch BEFORE UPDATE ON audit_log FOR EACH ROW EXECUTE FUNCTION touch_row();

-- Webhook outcomes per minute across ALL API servers (each flushes its own counts, additively).
CREATE TABLE webhook_stats (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bucket_start timestamptz NOT NULL CHECK (bucket_start = date_trunc('minute', bucket_start, 'UTC')),
  outcome      text NOT NULL,
  requests     bigint NOT NULL DEFAULT 0 CHECK (requests >= 0),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  deleted_at   timestamptz,
  metadata     jsonb NOT NULL DEFAULT '{}'
                 CONSTRAINT webhook_stats_metadata_ok CHECK (jsonb_typeof(metadata) = 'object')
) WITH (fillfactor = 70);
CREATE UNIQUE INDEX webhook_stats_live_key ON webhook_stats (bucket_start, outcome) WHERE deleted_at IS NULL;
CREATE TRIGGER webhook_stats_touch BEFORE UPDATE ON webhook_stats FOR EACH ROW EXECUTE FUNCTION touch_row();

-- Every running process (API or worker), refreshed by a heartbeat. Pool and work counters of
-- that process are in metadata: one place to see the whole fleet.
CREATE TABLE service_instances (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  instance     text NOT NULL,                -- role:host:pid:start
  role         text NOT NULL CHECK (role IN ('api', 'worker')),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  deleted_at   timestamptz,                  -- set on a clean shutdown
  metadata     jsonb NOT NULL DEFAULT '{}'
                 CONSTRAINT service_instances_metadata_ok CHECK (jsonb_typeof(metadata) = 'object'),
  CONSTRAINT service_instances_instance_key UNIQUE (instance)
) WITH (fillfactor = 70);
CREATE INDEX service_instances_seen ON service_instances (last_seen_at DESC) WHERE deleted_at IS NULL;
CREATE TRIGGER service_instances_touch BEFORE UPDATE ON service_instances FOR EACH ROW EXECUTE FUNCTION touch_row();

-- Recurring jobs. Any worker may run one: claiming is a single UPDATE that moves next_run_at,
-- so exactly one worker wins, with no leader, no advisory lock and no held session.
CREATE TABLE scheduled_jobs (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name             text NOT NULL CONSTRAINT scheduled_jobs_name_key UNIQUE,
  interval_seconds integer NOT NULL CHECK (interval_seconds > 0),
  next_run_at      timestamptz NOT NULL DEFAULT now(),
  last_run_at      timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  deleted_at       timestamptz,
  metadata         jsonb NOT NULL DEFAULT '{}' -- last result
                     CONSTRAINT scheduled_jobs_metadata_ok CHECK (jsonb_typeof(metadata) = 'object' AND pg_column_size(metadata) <= 16384)
);
CREATE INDEX scheduled_jobs_due ON scheduled_jobs (next_run_at) WHERE deleted_at IS NULL;
CREATE TRIGGER scheduled_jobs_touch BEFORE UPDATE ON scheduled_jobs FOR EACH ROW EXECUTE FUNCTION touch_row();

INSERT INTO scheduled_jobs (name, interval_seconds, next_run_at) VALUES
  ('reconcile_check', 3600, now() + interval '5 minutes'),
  ('retention', 3600, now() + interval '10 minutes');

-- usage_aggregate rows are updated on every call. Free space on each page keeps those updates
-- on the same page (HOT: no index writes), and eager vacuuming keeps hot rows short-chained.
ALTER TABLE usage_aggregate SET (fillfactor = 70, autovacuum_vacuum_scale_factor = 0.02,
                                 autovacuum_vacuum_threshold = 200);
-- The inbox churns through its pending index; vacuum well before 20% of a huge log is dead.
ALTER TABLE call_events SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.02);
