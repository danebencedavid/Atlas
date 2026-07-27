import pandas as pd

from atlas.anomalies import Anomaly
from atlas.regimes import classify_week


def _anomaly(metric: str, z: float, anomaly: float = 0.0) -> Anomaly:
    return Anomaly(metric, metric, 0.0, 0.0, anomaly, z, 50.0, "")


def test_classify_sunny_high_pressure_week():
    frame = pd.DataFrame(
        {
            "time": pd.date_range("2026-07-20", periods=168, freq="h", tz="UTC"),
            "temperature_2m": [25.0] * 168,
            "dew_point_2m": [12.0] * 168,
            "precipitation": [0.0] * 168,
            "wind_speed_10m": [2.5] * 168,
            "wind_speed_100m": [4.0] * 168,
            "wind_gusts_10m": [5.0] * 168,
            "pressure_msl": [1020.0] * 168,
            "cloud_cover": [20.0] * 168,
            "shortwave_radiation": [400.0] * 168,
            "sunshine_duration": [1800.0] * 168,
        }
    )
    anomalies = [
        _anomaly("temperature_mean_c", 0.2),
        _anomaly("precipitation_total_mm", -0.8),
        _anomaly("wind_speed_mean_ms", -0.2),
        _anomaly("pressure_mean_hpa", 0.3),
        _anomaly("cloud_cover_mean_pct", -1.0),
        _anomaly("shortwave_total_wh_m2", 1.2),
    ]

    result = classify_week(frame, anomalies)

    assert result.label == "Sunny high-pressure week"
    assert "above-normal radiation" in result.signals
