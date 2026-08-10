from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.hungaromet import StationObservations
from atlas.verification import MINIMUM_RELIABLE_PAIRS, verify_against_station


def _station(hours: int = 48, offset: float = 0.0) -> StationObservations:
    times = pd.date_range("2026-08-01", periods=hours, freq="h", tz="UTC")
    index = np.arange(hours, dtype=float)
    frame = pd.DataFrame(
        {
            "time": times,
            "station_id": 12345,
            "temperature_c": 18.0 + 5.0 * np.sin(index / 6.0) - offset,
            "relative_humidity_pct": 60.0 + 10.0 * np.cos(index / 5.0),
            "pressure_msl_hpa": 1012.0 + np.sin(index / 9.0),
            "wind_speed_ms": 3.0 + np.cos(index / 4.0),
            "wind_gust_ms": 6.0 + np.cos(index / 4.0),
            "precipitation_mm": np.where(index % 7 == 0, 1.2, 0.0),
        }
    )
    return StationObservations(frame=frame, station_id=12345, station_name="Debrecen Airport", notes=[])


def _reanalysis(hours: int = 48) -> pd.DataFrame:
    times = pd.date_range("2026-08-01", periods=hours, freq="h", tz="UTC")
    index = np.arange(hours, dtype=float)
    return pd.DataFrame(
        {
            "time": times,
            "temperature_2m": 18.0 + 5.0 * np.sin(index / 6.0),
            "relative_humidity_2m": 60.0 + 10.0 * np.cos(index / 5.0),
            "pressure_msl": 1012.0 + np.sin(index / 9.0),
            "wind_speed_10m": 3.0 + np.cos(index / 4.0),
            "wind_gusts_10m": 6.0 + np.cos(index / 4.0),
            "precipitation": np.where(index % 7 == 0, 1.2, 0.0),
        }
    )


def test_identical_series_score_as_perfect():
    result = verify_against_station(_reanalysis(), _station())
    assert result.hours_compared == 48
    assert result.station_name == "Debrecen Airport"
    temperature = result.headline
    assert temperature is not None
    assert temperature.key == "temperature_2m"
    assert temperature.bias == 0.0
    assert temperature.root_mean_square_error == 0.0
    assert temperature.correlation is not None
    assert temperature.correlation > 0.999
    assert temperature.reliable


def test_bias_is_reanalysis_minus_station():
    # The station reads 2 degrees cooler, so the reanalysis must score +2.
    result = verify_against_station(_reanalysis(), _station(offset=2.0))
    temperature = result.headline
    assert temperature is not None
    assert temperature.bias == pytest.approx(2.0)
    assert temperature.mean_absolute_error == pytest.approx(2.0)
    assert temperature.root_mean_square_error == pytest.approx(2.0)
    # A constant offset leaves the shape untouched.
    assert temperature.correlation is not None
    assert temperature.correlation > 0.999


def test_dew_point_is_derived_from_station_humidity():
    result = verify_against_station(_reanalysis().assign(dew_point_2m=10.0), _station())
    labels = {variable.key for variable in result.variables}
    assert "dew_point_2m" in labels


def test_non_overlapping_hours_report_no_variables():
    reanalysis = _reanalysis()
    reanalysis["time"] = reanalysis["time"] + pd.Timedelta(days=400)
    result = verify_against_station(reanalysis, _station())
    assert result.hours_compared == 0
    assert result.variables == []
    assert result.notes


def test_thin_samples_are_flagged_as_unreliable():
    hours = MINIMUM_RELIABLE_PAIRS - 2
    result = verify_against_station(_reanalysis(hours), _station(hours))
    temperature = result.headline
    assert temperature is not None
    assert not temperature.reliable
    assert any("indicative only" in note for note in result.notes)


def test_empty_station_frame_is_handled():
    empty = StationObservations(frame=pd.DataFrame(), station_id=None, station_name="none", notes=[])
    result = verify_against_station(_reanalysis(), empty)
    assert result.hours_compared == 0
    assert result.variables == []
