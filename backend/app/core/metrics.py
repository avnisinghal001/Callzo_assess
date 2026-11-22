"""Prometheus metrics. Queue gauges are read from Postgres at scrape time, so the API can
report on work done by the worker process. Every query uses a partial index."""

from collections.abc import Callable
from typing import ClassVar

import structlog
from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from psycopg_pool import ConnectionPool

log = structlog.get_logger()

PENDING_COUNT = (
    "SELECT count(*) AS n FROM call_events WHERE status = 'pending' AND deleted_at IS NULL"
)
DEAD_COUNT = "SELECT count(*) AS n FROM call_events WHERE status = 'dead' AND deleted_at IS NULL"
OLDEST_DUE = """
SELECT extract(epoch FROM now() - min(next_attempt_at)) AS lag
FROM call_events WHERE status = 'pending' AND deleted_at IS NULL
"""


class InboxCollector:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def collect(self):
        try:
            with self._pool.connection(timeout=2) as conn:
                pending = conn.execute(PENDING_COUNT).fetchone()["n"]
                dead = conn.execute(DEAD_COUNT).fetchone()["n"]
                lag = conn.execute(OLDEST_DUE).fetchone()["lag"]
        except Exception as exc:  # a failing scrape must not break /metrics for other series
            log.warning("inbox_metrics_unavailable", error=type(exc).__name__)
            return
        events = GaugeMetricFamily("inbox_events", "Events not yet processed", labels=["status"])
        events.add_metric(["pending"], pending)
        events.add_metric(["dead"], dead)
        yield events
        oldest = GaugeMetricFamily(
            "inbox_oldest_due_seconds", "Age of the oldest pending event past its due time"
        )
        oldest.add_metric([], max(float(lag or 0), 0.0))
        yield oldest


class PoolCollector:
    """Connection-pool saturation, from psycopg's own statistics. Watch requests_waiting and
    the wait time before raising max_size: queueing usually means slow queries, not too few
    connections."""

    GAUGES: ClassVar[dict[str, str]] = {
        "pool_size": "Connections currently open",
        "pool_available": "Idle connections ready to use",
        "requests_waiting": "Requests queued for a connection right now",
    }
    COUNTERS: ClassVar[dict[str, tuple[str, str]]] = {
        "requests_num": ("requests", "Connection checkouts"),
        "requests_queued": ("requests_queued", "Checkouts that had to wait"),
        "requests_errors": ("requests_errors", "Checkouts that failed (timeout or queue full)"),
        "connections_num": ("connections_opened", "Connections opened"),
        "connections_errors": ("connection_errors", "Failed attempts to open a connection"),
        "connections_lost": ("connections_lost", "Connections found broken"),
    }

    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def stats(self) -> dict[str, int]:
        return self._pool.get_stats()

    def collect(self):
        stats = self.stats()
        for key, doc in self.GAUGES.items():
            gauge = GaugeMetricFamily(f"db_{key}", doc)
            gauge.add_metric([], stats.get(key, 0))
            yield gauge
        for key, (name, doc) in self.COUNTERS.items():
            counter = CounterMetricFamily(f"db_pool_{name}", doc)
            counter.add_metric([], stats.get(key, 0))
            yield counter
        wait = CounterMetricFamily(
            "db_pool_wait_seconds", "Total time requests spent waiting for a connection"
        )
        wait.add_metric([], stats.get("requests_wait_ms", 0) / 1000)
        yield wait


class Metrics:
    """Per-process Prometheus metrics. `on_outcome` also feeds the cross-server statistics."""

    def __init__(self, pool: ConnectionPool, on_outcome: Callable[[str], None]):
        self.registry = CollectorRegistry()
        self._on_outcome = on_outcome
        self.webhook_requests = Counter(
            "webhook_requests_total",
            "Webhook requests by outcome",
            ["outcome"],
            registry=self.registry,
        )
        self.request_seconds = Histogram(
            "http_request_duration_seconds",
            "Request latency",
            ["method", "route", "status"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
            registry=self.registry,
        )
        self.pool_stats = PoolCollector(pool)
        self.registry.register(InboxCollector(pool))
        self.registry.register(self.pool_stats)

    def webhook(self, outcome: str) -> None:
        self.webhook_requests.labels(outcome).inc()
        self._on_outcome(outcome)

    def observe_request(self, method: str, route: str, status: int, seconds: float) -> None:
        self.request_seconds.labels(method, route, str(status)).observe(seconds)
