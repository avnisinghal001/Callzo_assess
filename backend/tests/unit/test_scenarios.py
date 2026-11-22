import random
from datetime import UTC, datetime

import pytest

from app.core.errors import AppError
from app.core.security import any_signature_is_valid
from app.modules.ops.scenarios import (
    BURST_SECONDS,
    LATE_DAYS,
    bad_signatures,
    build_scenario,
    expected_usage,
    malformed_bodies,
)
from app.modules.webhooks.service import parse_event

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def build(name, count=3):
    return build_scenario(name, "acct_001", count, NOW, random.Random(1))


def test_normal_is_started_then_ended_per_call():
    events = build("normal")
    assert [e.event_type for e in events] == ["call.started", "call.ended"] * 3
    assert all(a.call_id == b.call_id for a, b in zip(events[::2], events[1::2], strict=True))


def test_out_of_order_sends_ended_first():
    assert [e.event_type for e in build("out_of_order", 1)] == ["call.ended", "call.started"]


def test_duplicate_is_one_event_three_times():
    events = build("duplicate")
    assert len(events) == 3 and len({e.event_id for e in events}) == 1


def test_late_events_are_old():
    assert all((NOW - e.timestamp).days == LATE_DAYS for e in build("late"))


def test_burst_calls_are_long_and_cost_something():
    events = build("burst", 5)
    assert len(events) == 5 and all(e.duration_seconds == BURST_SECONDS for e in events)
    assert all(e.cost_cents > 0 for e in events)


def test_failed_calls_have_no_cost():
    assert all(e.cost_cents == 0 for e in build("failed"))


def test_event_ids_are_unique_across_calls():
    events = build("normal", 50)
    assert len({e.event_id for e in events}) == len(events)


def test_expected_usage_counts_each_event_id_once():
    once = expected_usage(build("duplicate"), NOW)
    assert (once.completed_calls, once.late_calls) == (1, 0)


def test_expected_usage_flags_late_calls():
    late = expected_usage(build("late"), NOW)
    assert late.late_calls == 3 and late.late_cost_cents == late.cost_cents > 0


def test_every_malformed_body_is_refused_as_a_client_error():
    for label, body in malformed_bodies("acct_001", NOW):
        with pytest.raises(AppError) as caught:
            parse_event(body)
        assert 400 <= caught.value.status_code < 500, label


def test_every_bad_signature_is_refused():
    for label, signature in bad_signatures(b"{}"):
        assert not any_signature_is_valid(["real-secret-real-secret"], b"{}", signature), label
