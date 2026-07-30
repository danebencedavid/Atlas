from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def last_complete_week(today: date | None = None, tz_name: str = "Europe/Budapest") -> tuple[date, date]:
    """Return the last complete Monday-Sunday local calendar week."""
    if today is None:
        today = datetime.now(ZoneInfo(tz_name)).date()
    current_week_monday = today - timedelta(days=today.weekday())
    start = current_week_monday - timedelta(days=7)
    end = current_week_monday - timedelta(days=1)
    return start, end


def last_complete_period(
    today: date | None = None,
    tz_name: str = "Europe/Budapest",
    days: int = 3,
) -> tuple[date, date]:
    """Return the most recent complete local-calendar-day window."""
    if days < 1:
        raise ValueError("Reporting window must contain at least one day.")
    if today is None:
        today = datetime.now(ZoneInfo(tz_name)).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return start, end


def local_period_to_utc_bounds(start: date, end: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(start, time.min, tzinfo=tz)
    end_exclusive_local = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_exclusive_local.astimezone(timezone.utc)


def local_week_to_utc_bounds(start: date, end: date, tz_name: str) -> tuple[datetime, datetime]:
    """Backward-compatible alias for callers using the former weekly name."""
    return local_period_to_utc_bounds(start, end, tz_name)
