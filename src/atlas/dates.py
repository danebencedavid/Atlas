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


def local_week_to_utc_bounds(start: date, end: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(start, time.min, tzinfo=tz)
    end_exclusive_local = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_exclusive_local.astimezone(timezone.utc)
