-- Read-only walkthrough of the simulator. Run after the inbox has drained.
-- docker compose exec -T postgres psql -X -U callzo -d callzo < scripts/scenarios.sql
-- These diagnostics can read whole tables. Request-path queries use separate indexes.

\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

\echo '== inbox: pending and dead should be empty after a clean simulator run'
SELECT status, count(*) AS events
FROM call_events WHERE deleted_at IS NULL
GROUP BY status ORDER BY status;

\echo '== normal and failed calls: resolved calls and billed usage'
SELECT status, count(*) AS calls, sum(duration_seconds) AS seconds, sum(cost_cents) AS cents
FROM calls WHERE deleted_at IS NULL
GROUP BY status ORDER BY status;

\echo '== duplicates: the stored event count should equal the distinct provider id count'
SELECT count(*) AS stored_events, count(DISTINCT provider_event_id) AS distinct_provider_ids
FROM call_events;

\echo '== webhook outcomes: duplicates and rejected deliveries recorded across API replicas'
SELECT outcome, sum(requests) AS deliveries
FROM webhook_stats WHERE deleted_at IS NULL
GROUP BY outcome ORDER BY outcome;

\echo '== out_of_order: completed calls whose terminal event arrived before their start'
SELECT a.external_id AS account, c.provider_call_id, c.status,
       c.started_at < c.ended_at AS provider_times_in_order
FROM calls c
JOIN accounts a ON a.id = c.account_id
JOIN call_events terminal ON terminal.id = c.terminal_event_id
WHERE c.deleted_at IS NULL AND c.status = 'completed'
  AND terminal.received_at < (
    SELECT min(started.received_at)
    FROM call_events started
    WHERE started.account_external_id = a.external_id
      AND started.provider_call_id = c.provider_call_id
      AND started.event_type = 'call.started' AND started.deleted_at IS NULL
  )
ORDER BY a.external_id, c.provider_call_id LIMIT 10;

\echo '== late: month buckets that include late calls'
SELECT a.external_id AS account, u.period_start AS month, u.completed_calls,
       u.late_calls, u.late_cost_cents
FROM usage_aggregate u JOIN accounts a ON a.id = u.account_id
WHERE u.period_type = 'month' AND u.deleted_at IS NULL AND u.late_calls > 0
ORDER BY a.external_id, u.period_start;

\echo '== cap_burst: current UTC month rows with a recorded cap crossing'
SELECT a.external_id AS account, u.period_start AS month, u.duration_seconds AS used_seconds,
       a.monthly_cap_minutes::bigint * 60 AS cap_seconds, u.cap_reached_at
FROM usage_aggregate u JOIN accounts a ON a.id = u.account_id
WHERE u.period_type = 'month' AND u.deleted_at IS NULL AND a.deleted_at IS NULL
  AND u.period_start = date_trunc('month', now() AT TIME ZONE 'UTC')::date
  AND u.cap_reached_at IS NOT NULL
ORDER BY a.external_id;

\echo '== proof: replay live terminal events and compare all six lifetime counters'
WITH winner AS (
  SELECT DISTINCT ON (a.external_id, e.provider_call_id)
         a.external_id, e.event_type = 'call.ended' AS completed, e.duration_seconds, e.cost_cents,
         e.received_at - e.occurred_at > interval '72 hours' AS late
  FROM call_events e JOIN accounts a ON a.external_id = e.account_external_id
  WHERE a.deleted_at IS NULL AND e.deleted_at IS NULL
    AND e.event_type IN ('call.ended', 'call.failed')
  ORDER BY a.external_id, e.provider_call_id, completed DESC, e.occurred_at DESC,
           e.provider_event_id COLLATE "C" DESC
), raw AS (
  SELECT external_id, count(*) FILTER (WHERE completed) AS completed_calls,
         count(*) FILTER (WHERE NOT completed) AS failed_calls,
         sum(duration_seconds) FILTER (WHERE completed) AS duration_seconds,
         sum(cost_cents) FILTER (WHERE completed) AS cost_cents,
         count(*) FILTER (WHERE late) AS late_calls,
         sum(cost_cents) FILTER (WHERE late AND completed) AS late_cost_cents
  FROM winner GROUP BY external_id
), stored AS (
  SELECT a.external_id, u.completed_calls, u.failed_calls, u.duration_seconds,
         u.cost_cents, u.late_calls, u.late_cost_cents
  FROM usage_aggregate u JOIN accounts a ON a.id = u.account_id
  WHERE a.deleted_at IS NULL AND u.deleted_at IS NULL AND u.period_type = 'lifetime'
)
SELECT coalesce(r.external_id, s.external_id) AS account,
       coalesce(r.cost_cents, 0) AS raw_cents, coalesce(s.cost_cents, 0) AS stored_cents,
       ROW(coalesce(r.completed_calls, 0), coalesce(r.failed_calls, 0),
           coalesce(r.duration_seconds, 0), coalesce(r.cost_cents, 0),
           coalesce(r.late_calls, 0), coalesce(r.late_cost_cents, 0)) =
       ROW(coalesce(s.completed_calls, 0), coalesce(s.failed_calls, 0),
           coalesce(s.duration_seconds, 0), coalesce(s.cost_cents, 0),
           coalesce(s.late_calls, 0), coalesce(s.late_cost_cents, 0)) AS matches
FROM raw r FULL JOIN stored s USING (external_id)
ORDER BY account;

COMMIT;
