from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.config import AtlasConfig
from atlas.forecast_verification import (
    build_truth_table,
    clear_sky_index,
    pair_forecasts_with_truth,
    score,
)
from atlas.hungaromet import StationObservations


def _station(hours: int = 48, start: str = "2026-08-01", offset: float = 0.0) -> StationObservations:
    times = pd.date_range(start, periods=hours * 6, freq="10min", tz="UTC")
    index = np.arange(len(times), dtype=float)
    frame = pd.DataFrame(
        {
            "time": times,
            "temperature_c": 15.0 + 5.0 * np.sin(index / 36.0) + offset,
            "wind_speed_ms": 4.0 + np.cos(index / 24.0),
            "wind_gust_ms": 8.0 + np.cos(index / 24.0),
            "relative_humidity_pct": 65.0 + 5.0 * np.cos(index / 30.0),
        }
    )
    return StationObservations(frame, 64711, "Debrecen Airport", [])


def _forecasts(hours: int = 48, start: str = "2026-08-01", bias: float = 1.0) -> pd.DataFrame:
    times = pd.date_range(start, periods=hours, freq="h", tz="UTC")
    index = np.arange(hours, dtype=float)
    return pd.DataFrame(
        {
            "valid_time_utc": times,
            "lead_time_hours": 24,
            "model": "best_match",
            "variable": "temperature_2m",
            "value": 15.0 + 5.0 * np.sin(index * 6.0 / 36.0) + bias,
            "retrieved_at": pd.Timestamp("2026-08-01", tz="UTC"),
        }
    )


def test_station_is_preferred_and_era5_only_fills_gaps():
    station = _station(hours=24)
    era5 = pd.DataFrame(
        {
            # Overlaps the station for 24 h, then extends 24 h beyond it.
            "time": pd.date_range("2026-08-01", periods=48, freq="h", tz="UTC"),
            "temperature_2m": np.full(48, -99.0),
        }
    )
    truth, notes = build_truth_table(station, era5)
    temperature = truth[truth["variable"] == "temperature_2m"]
    overlap = temperature[temperature["valid_time_utc"] < pd.Timestamp("2026-08-02", tz="UTC")]
    beyond = temperature[temperature["valid_time_utc"] >= pd.Timestamp("2026-08-02", tz="UTC")]
    # Where the station exists it wins; the sentinel ERA5 value never appears.
    assert set(overlap["truth_source"]) == {"station"}
    assert not (overlap["observed"] == -99.0).any()
    # Beyond the station record ERA5 fills in, explicitly marked.
    assert set(beyond["truth_source"]) == {"era5"}
    assert notes


def test_fallback_rows_are_marked_never_silently_substituted():
    era5 = pd.DataFrame(
        {
            "time": pd.date_range("2026-08-01", periods=6, freq="h", tz="UTC"),
            "temperature_2m": np.arange(6.0),
        }
    )
    truth, _ = build_truth_table(StationObservations(pd.DataFrame(), None, "none", []), era5)
    assert set(truth["truth_source"]) == {"era5"}
    assert "truth_source" in truth.columns


def test_naive_timestamps_are_rejected_rather_than_coerced():
    # A naive column silently localised would shift every pair by the UTC offset.
    forecasts = _forecasts()
    forecasts["valid_time_utc"] = forecasts["valid_time_utc"].dt.tz_localize(None)
    truth = pd.DataFrame(
        {
            "valid_time_utc": pd.date_range("2026-08-01", periods=4, freq="h"),
            "variable": "temperature_2m",
            "observed": [1.0, 2.0, 3.0, 4.0],
            "truth_source": "station",
        }
    )
    with pytest.raises(AssertionError, match="timezone-naive"):
        pair_forecasts_with_truth(forecasts, truth)


def test_pairs_join_on_the_same_utc_hour():
    station = _station(hours=48)
    truth, _ = build_truth_table(station, None)
    result = pair_forecasts_with_truth(_forecasts(hours=48), truth)
    assert result.available
    assert len(result.pairs) == 48
    # An hour shift would break this: forecast and observation must describe the
    # same instant.
    merged = result.pairs.sort_values("valid_time_utc")
    assert merged["valid_time_utc"].dt.hour.tolist() == [t % 24 for t in range(48)]


def test_error_is_forecast_minus_observation():
    station = _station(hours=24, offset=0.0)
    truth, _ = build_truth_table(station, None)
    # A forecast exactly 2 degrees warm must score bias +2.
    forecasts = _forecasts(hours=24, bias=0.0).copy()
    temperature_truth = truth[truth["variable"] == "temperature_2m"]
    observed = temperature_truth.set_index("valid_time_utc")["observed"]
    forecasts["value"] = forecasts["valid_time_utc"].map(observed) + 2.0
    result = pair_forecasts_with_truth(forecasts, truth)
    table = score(result.pairs, ["variable"])
    assert table["bias"].iloc[0] == pytest.approx(2.0, abs=1e-9)
    assert table["mae"].iloc[0] == pytest.approx(2.0, abs=1e-9)
    assert table["rmse"].iloc[0] == pytest.approx(2.0, abs=1e-9)


def test_scores_carry_sample_sizes():
    station = _station(hours=48)
    truth, _ = build_truth_table(station, None)
    result = pair_forecasts_with_truth(_forecasts(hours=48), truth)
    table = score(result.pairs, ["variable", "lead_time_hours", "model"])
    assert "n" in table.columns
    assert table["n"].sum() == len(result.pairs)


def test_rmse_is_at_least_mae():
    station = _station(hours=48)
    truth, _ = build_truth_table(station, None)
    result = pair_forecasts_with_truth(_forecasts(hours=48), truth)
    table = score(result.pairs, ["variable"])
    assert (table["rmse"] >= table["mae"] - 1e-9).all()


def test_clear_sky_regimes_split_daylight_and_leave_night_unlabelled():
    times = pd.date_range("2026-06-21T00:00Z", periods=24, freq="h", tz="UTC")
    pairs = pd.DataFrame(
        {
            "valid_time_utc": times,
            "variable": "shortwave_radiation",
            "observed": np.where((times.hour >= 6) & (times.hour <= 18), 600.0, 0.0),
            "value": 500.0,
            "error": 0.0,
        }
    )
    labelled = clear_sky_index(pairs, AtlasConfig())
    midday = labelled[labelled["valid_time_utc"].dt.hour == 12]
    night = labelled[labelled["valid_time_utc"].dt.hour == 0]
    assert midday["sky_regime"].notna().all()
    assert night["sky_regime"].isna().all()
    assert midday["clear_sky_index"].iloc[0] > 0


def test_empty_inputs_are_handled():
    result = pair_forecasts_with_truth(pd.DataFrame(), pd.DataFrame())
    assert not result.available
    assert result.notes
    assert score(pd.DataFrame(), ["variable"]).empty
