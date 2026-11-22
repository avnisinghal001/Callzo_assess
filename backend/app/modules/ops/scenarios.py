"""Synthetic traffic for the console sandbox. Pure: given a clock and an rng, returns events."""

import hashlib
import hmac
import json
import random
import uuid
from datetime import datetime, timedelta
from typing import Literal

from app.modules.aggregates.buckets import Usage
from app.modules.metering.call_state import LATE_AFTER
from app.modules.webhooks.schemas import CallEventIn

StoredScenario = Literal["normal", "failed", "duplicate", "out_of_order", "late", "burst"]
RejectedScenario = Literal["malformed", "bad_signature"]
Scenario = StoredScenario | RejectedScenario
LATE_DAYS = 35
BURST_SECONDS = 600


def _event(kind: str, account: str, call: str, when: datetime, duration: int = 0, event_id=None):
    ended = kind == "call.ended"
    return CallEventIn(
        event_id=event_id or f"sbx_{uuid.uuid4().hex[:16]}",
        event_type=kind,
        account_id=account,
        call_id=call,
        timestamp=when,
        duration_seconds=duration,
        cost_cents=max(duration // 30, 1) if ended else 0,
        destination_country="US",
    )


def build_scenario(
    scenario: StoredScenario, account: str, count: int, now: datetime, rng: random.Random
) -> list[CallEventIn]:
    def call_id() -> str:
        return f"sbx_call_{uuid.uuid4().hex[:12]}"

    events: list[CallEventIn] = []
    if scenario == "duplicate":
        one = _event("call.ended", account, call_id(), now, rng.randint(60, 900))
        return [one, one, one]  # identical event_id three times
    for _ in range(count):
        call, seconds = call_id(), rng.randint(60, 900)
        started = now - timedelta(seconds=seconds)
        match scenario:
            case "normal":
                events += [
                    _event("call.started", account, call, started),
                    _event("call.ended", account, call, now, seconds),
                ]
            case "failed":
                events += [
                    _event("call.started", account, call, started),
                    _event("call.failed", account, call, now),
                ]
            case "out_of_order":
                events += [
                    _event("call.ended", account, call, now, seconds),
                    _event("call.started", account, call, started),
                ]
            case "late":
                then = now - timedelta(days=LATE_DAYS)
                events.append(_event("call.ended", account, call, then, seconds))
            case "burst":
                events.append(_event("call.ended", account, call, now, BURST_SECONDS))
    return events


def expected_usage(events: list[CallEventIn], now: datetime) -> Usage:
    """What these events must add, counted the naive way. Deliberately not the metering code:
    it is what the metering result is judged against."""
    total = Usage()
    for event in {e.event_id: e for e in events}.values():
        late = now - event.timestamp > LATE_AFTER
        if event.event_type == "call.ended":
            total += Usage(
                completed_calls=1,
                duration_seconds=event.duration_seconds,
                cost_cents=event.cost_cents,
                late_calls=int(late),
                late_cost_cents=event.cost_cents if late else 0,
            )
        elif event.event_type == "call.failed":
            total += Usage(failed_calls=1, late_calls=int(late))
    return total


def malformed_bodies(account: str, now: datetime) -> list[tuple[str, bytes]]:
    good = _event("call.ended", account, "sbx_call_malformed", now, 60).model_dump(mode="json")
    encode = lambda value: json.dumps(value).encode()  # noqa: E731
    return [
        ("missing field", encode({k: v for k, v in good.items() if k != "call_id"})),
        ("wrong type", encode({**good, "duration_seconds": "sixty"})),
        ("unknown event type", encode({**good, "event_type": "call.teleported"})),
        ("truncated JSON", encode(good)[:40]),
        ("empty body", b""),
    ]


def bad_signatures(body: bytes) -> list[tuple[str, str | None]]:
    wrong = hmac.new(b"not-the-real-secret", body, hashlib.sha256).hexdigest()
    return [("no signature", None), ("garbage", "deadbeef"), ("signed with another secret", wrong)]
