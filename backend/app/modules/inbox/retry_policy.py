"""Retry schedule for failed events. Pure, so it is trivial to test."""

MAX_DELAY_SECONDS = 300


def backoff_seconds(attempts: int, jitter: float) -> float:
    """Exponential, capped, with jitter in [0, 1) spreading retries over the upper half.

    attempts=1 -> 1-2s, 2 -> 2-4s, 3 -> 4-8s ... capped at 150-300s.
    """
    base = min(2**attempts, MAX_DELAY_SECONDS)
    return base / 2 + (base / 2) * jitter
