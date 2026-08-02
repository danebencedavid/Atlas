import numpy as np
import pandas as pd

from atlas.fronts import FrontAnalysis
from atlas.hungaromet import LightningArchive, RadarArchive, StationObservations
from atlas.phenomena import detect_weather_phenomena
from atlas.profile import ModelProfile


def test_phenomena_detector_reports_observed_fog_heat_and_gusts():
    times = pd.date_range("2026-07-28", periods=6, freq="h", tz="UTC")
    station = pd.DataFrame(
        {
            "time": times,
            "temperature_c": [18, 18, 31, 32, 28, 25],
            "relative_humidity_pct": [99, 98, 45, 40, 55, 60],
            "visibility_m": [600, 800, 10000, 10000, 10000, 10000],
            "precipitation_mm": 0.0,
            "wind_speed_ms": 3.0,
            "wind_direction_deg": 180.0,
            "wind_gust_ms": [4, 5, 8, 17, 8, 6],
        }
    )
    weather = pd.DataFrame(
        {
            "time": times,
            "temperature_2m": station["temperature_c"],
            "snowfall": 0.0,
        }
    )
    analysis = detect_weather_phenomena(
        weather,
        StationObservations(station, 64711, "Debrecen Airport", []),
        RadarArchive([], np.array([]), np.array([]), np.empty((0, 0, 0)), np.empty((0, 0)), pd.DataFrame(), []),
        LightningArchive(pd.DataFrame(), pd.DataFrame(), []),
        FrontAnalysis([], pd.DataFrame(), []),
        ModelProfile(pd.DataFrame(), None, "model", {}, []),
        "Europe/Budapest",
    )

    kinds = {event.kind for event in analysis.events}
    assert {"Fog", "Heat stress", "Strong gusts"}.issubset(kinds)
    assert all(event.source == "HungaroMet station 64711" for event in analysis.events)
