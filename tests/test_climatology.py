from datetime import date
from pathlib import Path

import pandas as pd

from atlas.climatology import build_climate_reference, fetch_climate_archive, period_table
from atlas.config import AtlasConfig, ClimatologyConfig, OutputConfig


def _archive(first_year: int, final_year: int) -> pd.DataFrame:
    dates = pd.date_range(f"{first_year}-01-01", f"{final_year}-12-31", freq="D")
    return pd.DataFrame(
        {
            "date": dates.date,
            "temperature_2m_mean": [float(timestamp.year - 1990) for timestamp in dates],
            "precipitation_sum": 1.0,
            "wind_speed_100m_mean": 5.0,
            "pressure_msl_mean": 1012.0,
            "cloud_cover_mean": 50.0,
            "shortwave_radiation_sum": 10.0,
            "et0_fao_evapotranspiration_sum": 2.0,
        }
    )


def test_period_table_maps_same_calendar_window_and_aggregates_energy_units():
    table = period_table(
        _archive(1991, 1993),
        date(2026, 7, 28),
        date(2026, 7, 30),
        1991,
        1993,
    )

    assert len(table) == 3
    assert table.loc[0, "precipitation_total_mm"] == 3.0
    assert round(table.loc[0, "shortwave_total_wh_m2"], 1) == 8333.3
    assert table.loc[0, "water_balance_mm"] == -3.0


def test_climate_reference_separates_standard_recent_and_full_record():
    archive = _archive(1940, 2025)
    current = {
        "temperature_mean_c": 35.0,
        "precipitation_total_mm": 0.0,
        "wind_speed_mean_ms": 5.0,
        "pressure_mean_hpa": 1012.0,
        "cloud_cover_mean_pct": 50.0,
        "shortwave_total_wh_m2": 8000.0,
    }
    reference = build_climate_reference(
        AtlasConfig(), archive, current, date(2026, 7, 28), date(2026, 7, 30)
    )

    assert len(reference.standard_table) == 30
    assert len(reference.recent_table) == 10
    assert len(reference.full_record_table) == 36
    assert any("1990-2025" in note for note in reference.notes)
    assert reference.full_record_percentiles["temperature_mean_c"] > 50


def test_climate_archive_uses_immutable_annual_caches(monkeypatch, tmp_path: Path):
    requested_years: list[int] = []

    def fake_fetch(_url, params):
        year = int(params["start_date"][:4])
        requested_years.append(year)
        return {
            "daily": {
                "time": [f"{year}-07-01"],
                "temperature_2m_mean": [20.0],
                "precipitation_sum": [1.0],
                "wind_speed_100m_mean": [5.0],
                "pressure_msl_mean": [1012.0],
                "cloud_cover_mean": [50.0],
                "shortwave_radiation_sum": [10.0],
                "et0_fao_evapotranspiration_sum": [2.0],
            }
        }

    monkeypatch.setattr("atlas.climatology.fetch_json_with_retry", fake_fetch)
    config = AtlasConfig(
        climatology=ClimatologyConfig(archive_start_year=2020),
        outputs=OutputConfig(data_dir=tmp_path / "data"),
    )

    first = fetch_climate_archive(config, date(2023, 7, 2))
    assert sorted(requested_years) == [2020, 2021, 2022]
    assert len(first) == 3
    assert len(list((tmp_path / "data" / "raw").glob("open_meteo_era5_daily_????.json"))) == 3

    requested_years.clear()
    second = fetch_climate_archive(config, date(2023, 7, 2), refresh=True)
    assert requested_years == []
    assert second.equals(first)
