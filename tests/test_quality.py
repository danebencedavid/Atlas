from datetime import date

import pandas as pd

from atlas.quality import expected_hour_count, validate_hourly_week


def test_expected_hour_count_handles_regular_local_week():
    assert expected_hour_count(date(2026, 7, 20), date(2026, 7, 26), "Europe/Budapest") == 168


def test_expected_hour_count_handles_daylight_saving_transition():
    assert expected_hour_count(date(2026, 3, 23), date(2026, 3, 29), "Europe/Budapest") == 167


def test_validate_hourly_week_rejects_sparse_required_columns():
    times = pd.date_range("2026-07-19 22:00", periods=168, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "time": times,
            "temperature_2m": [20.0] * 168,
            "dew_point_2m": [10.0] * 168,
            "precipitation": [0.0] * 168,
            "cloud_cover": [50.0] * 168,
            "pressure_msl": [1012.0] * 168,
            "wind_speed_10m": [3.0] * 168,
            "wind_direction_10m": [180.0] * 168,
            "wind_gusts_10m": [6.0] * 168,
            "shortwave_radiation": [None] * 168,
        }
    )

    report = validate_hourly_week(frame, date(2026, 7, 20), date(2026, 7, 26), "Europe/Budapest")

    assert not report.ok
    assert report.sparse_columns == ["shortwave_radiation"]
