import pytest

from app.modules.usage.cap import cap_view

CAP_MIN = 5  # 300 seconds


@pytest.mark.parametrize(
    ("used", "status", "allowed"),
    [
        (0, "ok", True),
        (239, "ok", True),
        (240, "warning", True),  # exactly 80%
        (299, "warning", True),
        (300, "reached", False),  # exactly the cap: stop here
        (301, "exceeded", False),
    ],
)
def test_boundaries(used, status, allowed):
    view = cap_view(used, CAP_MIN, None)
    assert (view.status, view.new_calls_allowed) == (status, allowed)


def test_remaining_and_overage_never_go_negative():
    assert (
        cap_view(100, CAP_MIN, None).remaining_seconds,
        cap_view(100, CAP_MIN, None).overage_seconds,
    ) == (200, 0)
    assert (
        cap_view(400, CAP_MIN, None).remaining_seconds,
        cap_view(400, CAP_MIN, None).overage_seconds,
    ) == (0, 100)


def test_zero_cap_means_no_calls_allowed():
    assert not cap_view(0, 0, None).new_calls_allowed
