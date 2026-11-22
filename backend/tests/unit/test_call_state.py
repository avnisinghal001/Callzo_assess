import itertools
import uuid
from datetime import timedelta

from app.modules.metering.call_state import CallEvent, resolve_call, usage_of
from tests.helpers import at

T0 = at("2026-11-10T10:00:00")


def ev(event_id, kind, *, offset=0, duration=0, cost=0, received_delay=0):
    when = T0 + timedelta(seconds=offset)
    return CallEvent(
        uuid.uuid5(uuid.NAMESPACE_OID, event_id),
        event_id,
        kind,
        when,
        when + timedelta(seconds=received_delay),
        duration,
        cost,
    )


STARTED = ev("e1", "call.started")
ENDED = ev("e2", "call.ended", offset=180, duration=180, cost=6)


def test_every_arrival_order_gives_the_same_state():
    states = {resolve_call(list(p)) for p in itertools.permutations([STARTED, ENDED])}
    assert len(states) == 1
    state = states.pop()
    assert (state.status, state.duration_seconds, state.cost_cents) == ("completed", 180, 6)
    assert state.started_at == T0 and str(state.usage_date) == "2026-11-10"


def test_only_started_is_in_progress_and_costs_nothing():
    state = resolve_call([STARTED])
    assert state.status == "in_progress" and usage_of(state).is_zero()


def test_ended_before_started_still_completes():
    assert resolve_call([ENDED]).status == "completed"


def test_failed_contributes_a_failure_but_no_cost():
    usage = usage_of(
        resolve_call([STARTED, ev("e3", "call.failed", offset=5, duration=99, cost=9)])
    )
    assert (usage.failed_calls, usage.completed_calls, usage.cost_cents) == (1, 0, 0)
    assert usage.duration_seconds == 0


def test_ended_beats_failed_whatever_the_timestamps():
    failed_later = ev("e9", "call.failed", offset=999)
    for events in itertools.permutations([ENDED, failed_later]):
        assert resolve_call(list(events)).status == "completed"


def test_ties_break_deterministically():
    a = ev("a", "call.ended", duration=10, cost=1)
    b = ev("b", "call.ended", duration=20, cost=2)
    assert resolve_call([a, b]) == resolve_call([b, a])
    assert resolve_call([a, b]).terminal_event_id == uuid.uuid5(uuid.NAMESPACE_OID, "b")


def test_late_flag_uses_receipt_delay():
    on_time = resolve_call([ev("x", "call.ended", received_delay=3600, duration=1, cost=1)])
    late = resolve_call([ev("y", "call.ended", received_delay=35 * 86400, duration=1, cost=1)])
    assert not on_time.is_late and late.is_late
    assert usage_of(late).late_calls == 1 and usage_of(late).late_cost_cents == 1


def test_usage_date_is_the_utc_day_of_the_terminal_event():
    near_midnight = ev("m", "call.ended", offset=13 * 3600 + 59 * 60 + 59, duration=1, cost=1)
    assert str(resolve_call([near_midnight]).usage_date) == "2026-11-10"
    assert str(resolve_call([ev("n", "call.ended", offset=14 * 3600)]).usage_date) == "2026-11-11"
