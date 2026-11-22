"""Each API process counts webhook outcomes in memory and reports them, with a heartbeat, every
few seconds. Requests never wait for it; if Postgres is down the counts are kept and retried."""

import os
import socket
import threading
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import psycopg
import structlog
from psycopg_pool import ConnectionPool

from app.modules.fleet import repository as fleet

log = structlog.get_logger()


def instance_name(role: str) -> str:
    return f"{role}:{socket.gethostname()}:{os.getpid()}:{int(time.time())}"


class FleetReporter:
    def __init__(self, pool: ConnectionPool, describe: Callable[[], dict[str, Any]], every: float):
        self.instance = instance_name("api")
        self._pool, self._describe, self._every = pool, describe, every
        self._counts: Counter[tuple[datetime, str]] = Counter()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="fleet-reporter", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def count(self, outcome: str) -> None:
        minute = datetime.now(UTC).replace(second=0, microsecond=0)
        with self._lock:
            self._counts[(minute, outcome)] += 1

    def flush(self) -> None:
        with self._lock:
            pending, self._counts = self._counts, Counter()
        try:
            with self._pool.connection() as conn:
                if pending:
                    fleet.add_outcomes(conn, pending)
                fleet.heartbeat(conn, self.instance, "api", self._describe())
        except psycopg.Error as exc:
            with self._lock:
                self._counts.update(pending)  # nothing is lost; try again next time
            log.warning("fleet_report_failed", error=type(exc).__name__)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.flush()
        try:
            with self._pool.connection() as conn:
                fleet.sign_off(conn, self.instance)
        except psycopg.Error:
            log.warning("fleet_sign_off_failed")

    def _run(self) -> None:
        while not self._stop.wait(self._every):
            self.flush()
