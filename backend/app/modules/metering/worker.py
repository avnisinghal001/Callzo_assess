"""Background worker: drains the inbox, retries failures, runs scheduled jobs when idle.

Run any number of replicas on any number of servers: they coordinate only through Postgres.

Each event takes two short transactions: claim (bumps attempts, leases the event) and process
(meter + mark done). A worker that dies in between leaves an event that becomes due again when
the lease expires, with its attempt already counted: a poison event goes dead, never loops.
"""

import random
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path

import psycopg
import structlog

from app.core.config import Settings, load_settings
from app.core.db import Conn, connect
from app.core.logging import configure_logging
from app.modules.fleet import repository as fleet
from app.modules.fleet.reporter import instance_name
from app.modules.inbox import repository as inbox
from app.modules.inbox.retry_policy import backoff_seconds
from app.modules.jobs.service import run_due_job
from app.modules.metering.service import apply_event

log = structlog.get_logger()


def process_next(
    conn: Conn,
    *,
    max_attempts: int,
    lease_seconds: float = 60.0,
    jitter: Callable[[], float] = random.random,
) -> bool:
    """Claim and process one due event. False if nothing was due. `conn` must be idle."""
    with conn.transaction():
        event = inbox.claim_due(conn, lease_seconds)
    if event is None:
        return False

    if event.attempts > max_attempts:  # claimed too many times without ever finishing
        with conn.transaction():
            inbox.mark_dead(
                conn, event.id, f"gave up after {max_attempts} attempts (worker crash?)"
            )
        log.error("event_dead", event_id=event.provider_event_id, attempts=event.attempts)
        return True

    try:
        with conn.transaction():  # one atomic unit: usage change + marking the event done
            apply_event(conn, event)
            inbox.mark_processed(conn, event.id)
    except psycopg.OperationalError:
        raise  # connection trouble is not the event's fault; reconnect, the lease will expire
    except Exception as exc:
        with conn.transaction():
            status = inbox.mark_failed(
                conn,
                event.id,
                f"{type(exc).__name__}: {exc}",
                backoff_seconds(event.attempts, jitter()),
                max_attempts,
            )
        log.warning(
            "event_failed",
            event_id=event.provider_event_id,
            attempts=event.attempts,
            status=status,
            error=type(exc).__name__,
        )
    return True


def drain(conn: Conn, *, max_attempts: int, lease_seconds: float = 60.0) -> int:
    handled = 0
    while process_next(conn, max_attempts=max_attempts, lease_seconds=lease_seconds):
        handled += 1
    return handled


class Pulse:
    """Tells the outside world this worker is alive: a row for the console, a file for Docker.
    Beaten from the work loop itself, so a stuck loop goes silent instead of looking healthy."""

    def __init__(self, settings: Settings):
        self.instance = instance_name("worker")
        self.handled = 0
        self._every = settings.worker_heartbeat_seconds
        self._file = Path(settings.worker_alive_file)
        self._next = 0.0

    def beat(self, conn: Conn) -> None:
        if time.monotonic() < self._next:
            return
        self._next = time.monotonic() + self._every
        with conn.transaction():
            fleet.heartbeat(conn, self.instance, "worker", {"events_handled": self.handled})
        self._file.touch()  # last: healthy means the heartbeat really reached the database


def run(settings: Settings, stop: threading.Event) -> None:
    pulse = Pulse(settings)
    while not stop.is_set():
        try:
            # autocommit: every `conn.transaction()` is then a real commit. Without it, one stray
            # read opens a transaction and all later "commits" silently become savepoints.
            with connect(settings, autocommit=True) as conn:
                log.info("worker_started", instance=pulse.instance)
                while not stop.is_set():
                    pulse.beat(conn)
                    busy = process_next(
                        conn,
                        max_attempts=settings.max_attempts,
                        lease_seconds=settings.claim_lease_seconds,
                    )
                    if busy:
                        pulse.handled += 1
                    elif run_due_job(conn, settings) is None:
                        stop.wait(settings.worker_poll_seconds)
                with conn.transaction():
                    fleet.sign_off(conn, pulse.instance)
        except psycopg.OperationalError as exc:
            log.error("worker_connection_lost", error=type(exc).__name__)
            stop.wait(2)


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run(settings, stop)  # SIGTERM: finishes the event in hand, then signs off
    log.info("worker_stopped")


if __name__ == "__main__":
    main()
