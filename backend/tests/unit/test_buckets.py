import random
from datetime import date, timedelta

import pytest

from app.modules.aggregates.buckets import (
    LIFETIME_START,
    Bucket,
    Period,
    Usage,
    buckets_for_day,
    decompose_range,
    deltas_for_change,
    span,
)

U = Usage(completed_calls=1, duration_seconds=60, cost_cents=2)


def test_a_day_belongs_to_four_buckets():
    assert buckets_for_day(date(2026, 11, 10)) == (
        Bucket(Period.DAY, date(2026, 11, 10)),
        Bucket(Period.WEEK, date(2026, 11, 9)),  # Monday
        Bucket(Period.MONTH, date(2026, 11, 1)),
        Bucket(Period.LIFETIME, LIFETIME_START),
    )


def test_first_contribution_adds_to_four_buckets():
    deltas = deltas_for_change(None, Usage(), date(2026, 11, 10), U)
    assert len(deltas) == 4 and all(v == U for v in deltas.values())


def test_replay_changes_nothing():
    assert deltas_for_change(date(2026, 11, 10), U, date(2026, 11, 10), U) == {}


def test_correction_failed_to_completed_only_changes_the_difference():
    failed = Usage(failed_calls=1)
    deltas = deltas_for_change(date(2026, 11, 10), failed, date(2026, 11, 10), U)
    assert set(deltas.values()) == {U - failed}


def test_moving_between_months_cancels_shared_lifetime_bucket():
    deltas = deltas_for_change(date(2026, 10, 31), U, date(2026, 11, 1), U)
    assert Bucket(Period.LIFETIME, LIFETIME_START) not in deltas
    assert deltas[Bucket(Period.MONTH, date(2026, 10, 1))] == Usage() - U
    assert deltas[Bucket(Period.MONTH, date(2026, 11, 1))] == U


def test_deltas_are_sorted_for_a_stable_lock_order():
    deltas = deltas_for_change(date(2026, 12, 3), U, date(2026, 11, 10), U)
    assert list(deltas) == sorted(deltas)


def covered(buckets):
    days = []
    for b in buckets:
        first, last = span(b)
        days += [first + timedelta(days=i) for i in range((last - first).days + 1)]
    return days


@pytest.mark.parametrize("seed", range(300))
def test_decomposition_tiles_the_range_exactly(seed):
    rng = random.Random(seed)
    start = date(2025, 1, 1) + timedelta(days=rng.randrange(900))
    end = start + timedelta(days=rng.randrange(0, 800))
    days = covered(decompose_range(start, end))
    assert days == [start + timedelta(days=i) for i in range((end - start).days + 1)]


def test_decomposition_reads_few_buckets_for_long_ranges():
    buckets = decompose_range(date(2024, 1, 3), date(2026, 11, 22))  # ~1,050 days
    assert len(buckets) < 70
    assert sum(1 for b in buckets if b.period is Period.MONTH) == 33


def test_decomposition_edge_cases():
    assert decompose_range(date(2026, 11, 10), date(2026, 11, 10)) == [
        Bucket(Period.DAY, date(2026, 11, 10))
    ]
    assert decompose_range(date(2026, 11, 1), date(2026, 11, 30)) == [
        Bucket(Period.MONTH, date(2026, 11, 1))
    ]
    with pytest.raises(ValueError):
        decompose_range(date(2026, 11, 2), date(2026, 11, 1))
