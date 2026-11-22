"""Time helpers. Everything is timezone-aware UTC; a naive datetime is a bug."""

from datetime import UTC, date, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_date(moment: datetime) -> date:
    return moment.astimezone(UTC).date()


def week_start(day: date) -> date:
    """Monday of the ISO week containing `day`."""
    return day - timedelta(days=day.weekday())


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month_start(day: date) -> date:
    first = month_start(day)
    return (first + timedelta(days=32)).replace(day=1)


def month_end(day: date) -> date:
    return next_month_start(day) - timedelta(days=1)
