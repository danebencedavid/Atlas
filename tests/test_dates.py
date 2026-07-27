from datetime import date

from atlas.dates import last_complete_week


def test_last_complete_week_on_monday_returns_prior_monday_sunday():
    start, end = last_complete_week(today=date(2026, 7, 27))

    assert start == date(2026, 7, 20)
    assert end == date(2026, 7, 26)


def test_last_complete_week_midweek_still_returns_previous_full_week():
    start, end = last_complete_week(today=date(2026, 7, 30))

    assert start == date(2026, 7, 20)
    assert end == date(2026, 7, 26)
