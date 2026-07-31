from datetime import date

import numpy as np
import pandas as pd

from atlas.config import AtlasConfig
from atlas.energy import compute_physical_energy
from atlas.fronts import detect_fronts
from atlas.hungaromet import _parse_station_csv


def test_hungaromet_station_parser_normalizes_core_variables():
    payload = """# StationNumber: 64711
# StationName: Debrecen Airport
Time;r;t;v;p;u;fs;fsd;fx
202607280000;0.0;19.4;10000;1013.2;74;2.5;220;4.8
202607280010;0.2;19.1;9000;1013.1;76;2.8;225;5.1
"""

    frame = _parse_station_csv(payload)

    assert list(frame["station_id"].unique()) == [64711]
    assert frame["temperature_c"].tolist() == [19.4, 19.1]
    assert frame["precipitation_mm"].sum() == 0.2
    assert str(frame["time"].dt.tz) == "UTC"


def test_objective_front_detector_finds_compound_cold_passage():
    times = pd.date_range("2026-07-28", periods=16, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "time": times,
            "temperature_c": [24.0] * 8 + [17.0] * 8,
            "dew_point_c": [16.0] * 8 + [10.0] * 8,
            "pressure_msl_hpa": [1008.0] * 8 + [1013.0] * 8,
            "wind_speed_ms": [3.0] * 8 + [7.0] * 8,
            "wind_direction_deg": [190.0] * 8 + [320.0] * 8,
            "wind_gust_ms": [5.0] * 8 + [13.0] * 8,
            "precipitation_mm": [0.0] * 7 + [3.0, 2.0] + [0.0] * 7,
        }
    )

    analysis = detect_fronts(frame)

    assert analysis.events
    assert analysis.events[0].kind == "Probable cold-front passage"
    assert analysis.events[0].confidence >= 0.6


def test_physical_energy_model_returns_bounded_capacity_factors():
    times = pd.date_range("2026-07-28", periods=72, freq="h", tz="UTC")
    hour = times.hour.to_numpy()
    solar = np.maximum(0.0, 750.0 * np.sin(np.pi * (hour - 4) / 16.0))
    frame = pd.DataFrame(
        {
            "time": times,
            "temperature_2m": 20.0 + 7.0 * np.sin(2.0 * np.pi * (hour - 6) / 24.0),
            "relative_humidity_2m": np.full(72, 60.0),
            "pressure_msl": np.full(72, 1013.0),
            "wind_speed_10m": np.full(72, 4.5),
            "wind_speed_100m": np.full(72, 7.0),
            "shortwave_radiation": solar,
            "direct_radiation": solar * 0.7,
            "diffuse_radiation": solar * 0.3,
        }
    )

    energy = compute_physical_energy(AtlasConfig(), frame)

    assert energy.pv_yield_kwh_per_kwp > 0
    assert 0 < energy.pv_capacity_factor_pct < 100
    assert 0 < energy.wind_capacity_factor_pct < 100
    assert energy.mean_wind_power_density_w_m2 > 0
    assert energy.peak_pv_time is not None
    assert energy.peak_wind_time is not None
