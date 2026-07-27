import pandas as pd

from atlas.anomalies import compute_anomalies


def test_compute_anomalies_uses_baseline_mean_and_percentile():
    current = {
        "temperature_mean_c": 22.0,
        "precipitation_total_mm": 5.0,
        "wind_speed_mean_ms": 4.0,
        "pressure_mean_hpa": 1015.0,
        "cloud_cover_mean_pct": 40.0,
        "shortwave_total_wh_m2": 5000.0,
    }
    baseline = pd.DataFrame(
        {
            "temperature_mean_c": [18.0, 20.0, 21.0],
            "precipitation_total_mm": [1.0, 4.0, 8.0],
            "wind_speed_mean_ms": [3.0, 4.0, 5.0],
            "pressure_mean_hpa": [1010.0, 1014.0, 1016.0],
            "cloud_cover_mean_pct": [35.0, 45.0, 55.0],
            "shortwave_total_wh_m2": [4200.0, 4500.0, 4800.0],
        }
    )

    anomalies = {item.metric: item for item in compute_anomalies(current, baseline)}

    assert anomalies["temperature_mean_c"].baseline_mean == 19.666666666666668
    assert round(anomalies["temperature_mean_c"].anomaly, 2) == 2.33
    assert anomalies["shortwave_total_wh_m2"].percentile == 100.0
