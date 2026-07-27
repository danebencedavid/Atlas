from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


METRIC_LABELS = {
    "temperature_mean_c": "Temperature",
    "precipitation_total_mm": "Precipitation",
    "wind_speed_mean_ms": "Wind",
    "pressure_mean_hpa": "Pressure",
    "cloud_cover_mean_pct": "Cloud",
    "shortwave_total_wh_m2": "Solar radiation",
}


@dataclass(frozen=True)
class Anomaly:
    metric: str
    label: str
    value: float
    baseline_mean: float
    anomaly: float
    z_score: float
    percentile: float
    unit: str


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def weekly_metrics(frame: pd.DataFrame) -> dict[str, float]:
    wind_source = "wind_speed_100m" if "wind_speed_100m" in frame and _series(frame, "wind_speed_100m").notna().any() else "wind_speed_10m"
    return {
        "temperature_mean_c": float(_series(frame, "temperature_2m").mean()),
        "dew_point_mean_c": float(_series(frame, "dew_point_2m").mean()),
        "precipitation_total_mm": float(_series(frame, "precipitation").sum()),
        "wind_speed_mean_ms": float(_series(frame, wind_source).mean()),
        "wind_gust_max_ms": float(_series(frame, "wind_gusts_10m").max()),
        "pressure_mean_hpa": float(_series(frame, "pressure_msl").mean()),
        "pressure_range_hpa": float(_series(frame, "pressure_msl").max() - _series(frame, "pressure_msl").min()),
        "cloud_cover_mean_pct": float(_series(frame, "cloud_cover").mean()),
        "shortwave_total_wh_m2": float(_series(frame, "shortwave_radiation").sum()),
        "sunshine_total_s": float(_series(frame, "sunshine_duration").sum()),
        "frost_hours": float((_series(frame, "temperature_2m") <= 0).sum()),
        "cooling_degree_days_c": float(np.maximum(_series(frame, "temperature_2m") - 18.0, 0).sum() / 24.0),
        "heating_degree_days_c": float(np.maximum(18.0 - _series(frame, "temperature_2m"), 0).sum() / 24.0),
    }


def baseline_metric_table(baseline_frame: pd.DataFrame) -> pd.DataFrame:
    if "baseline_year" not in baseline_frame:
        raise ValueError("Baseline frame must include a baseline_year column.")
    rows = []
    for year, group in baseline_frame.groupby("baseline_year"):
        row = weekly_metrics(group)
        row["baseline_year"] = int(year)
        rows.append(row)
    return pd.DataFrame(rows)


def percentile_rank(value: float, samples: Iterable[float]) -> float:
    sample_array = np.asarray([sample for sample in samples if np.isfinite(sample)], dtype=float)
    if sample_array.size == 0 or not np.isfinite(value):
        return float("nan")
    return float((sample_array <= value).mean() * 100.0)


def compute_anomalies(current: dict[str, float], baseline_table: pd.DataFrame) -> list[Anomaly]:
    units = {
        "temperature_mean_c": "deg C",
        "precipitation_total_mm": "mm",
        "wind_speed_mean_ms": "m/s",
        "pressure_mean_hpa": "hPa",
        "cloud_cover_mean_pct": "%",
        "shortwave_total_wh_m2": "Wh/m2",
    }
    anomalies: list[Anomaly] = []
    for metric, label in METRIC_LABELS.items():
        samples = pd.to_numeric(baseline_table[metric], errors="coerce").dropna()
        baseline_mean = float(samples.mean())
        baseline_std = float(samples.std(ddof=0))
        value = float(current[metric])
        anomaly = value - baseline_mean
        z_score = anomaly / baseline_std if baseline_std > 0 else 0.0
        anomalies.append(
            Anomaly(
                metric=metric,
                label=label,
                value=value,
                baseline_mean=baseline_mean,
                anomaly=anomaly,
                z_score=float(z_score),
                percentile=percentile_rank(value, samples),
                unit=units[metric],
            )
        )
    return anomalies


def anomalies_as_frame(anomalies: list[Anomaly]) -> pd.DataFrame:
    return pd.DataFrame([anomaly.__dict__ for anomaly in anomalies])
