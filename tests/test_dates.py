from datetime import date

from atlas.dates import last_complete_period, last_complete_week


def test_last_complete_week_on_monday_returns_prior_monday_sunday():
    start, end = last_complete_week(today=date(2026, 7, 27))

    assert start == date(2026, 7, 20)
    assert end == date(2026, 7, 26)


def test_last_complete_week_midweek_still_returns_previous_full_week():
    start, end = last_complete_week(today=date(2026, 7, 30))

    assert start == date(2026, 7, 20)
    assert end == date(2026, 7, 26)


def test_last_complete_period_returns_previous_three_local_days():
    start, end = last_complete_period(today=date(2026, 7, 30), days=3)

    assert start == date(2026, 7, 27)
    assert end == date(2026, 7, 29)


def test_last_complete_period_rejects_empty_window():
    try:
        last_complete_period(today=date(2026, 7, 30), days=0)
    except ValueError as exc:
        assert "at least one day" in str(exc)
    else:
        raise AssertionError("Expected a ValueError for a zero-day window.")
