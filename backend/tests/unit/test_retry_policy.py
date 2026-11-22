from app.modules.inbox.retry_policy import MAX_DELAY_SECONDS, backoff_seconds


def test_grows_exponentially_with_jitter_inside_bounds():
    for attempts in range(1, 6):
        low, high = backoff_seconds(attempts, 0.0), backoff_seconds(attempts, 0.999)
        assert low == 2**attempts / 2 and low <= high < 2**attempts


def test_is_capped():
    assert backoff_seconds(50, 0.999) < MAX_DELAY_SECONDS
