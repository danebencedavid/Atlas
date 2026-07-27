from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EnergyIndex:
    solar_index: float
    wind_index: float
    combined_score: float
    calm_wind_penalty: float
    cloud_penalty: float
    label: str


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    if not np.isfinite(value):
        return 50.0
    return float(min(max(value, lower), upper))


def ratio_index(value: float, baseline: float) -> float:
    if not np.isfinite(value) or not np.isfinite(baseline) or baseline <= 0:
        return 50.0
    return clamp(100.0 * value / baseline)


def compute_energy_index(current: dict[str, float], baseline: dict[str, float]) -> EnergyIndex:
    solar_raw = ratio_index(current["shortwave_total_wh_m2"], baseline["shortwave_total_wh_m2"])
    cloud_excess = max(current["cloud_cover_mean_pct"] - baseline["cloud_cover_mean_pct"], 0.0)
    cloud_penalty = clamp(cloud_excess * 0.35, 0.0, 30.0)
    solar_index = clamp(solar_raw - cloud_penalty)

    wind_ratio = ratio_index(current["wind_speed_mean_ms"] ** 3, baseline["wind_speed_mean_ms"] ** 3)
    calm_wind_penalty = clamp(max(3.0 - current["wind_speed_mean_ms"], 0.0) * 12.0, 0.0, 36.0)
    wind_index = clamp(wind_ratio - calm_wind_penalty)

    combined = clamp((solar_index + wind_index) / 2.0)
    if solar_index >= wind_index + 10:
        label = "solar-favored"
    elif wind_index >= solar_index + 10:
        label = "wind-favored"
    else:
        label = "balanced renewable"

    return EnergyIndex(
        solar_index=round(solar_index, 1),
        wind_index=round(wind_index, 1),
        combined_score=round(combined, 1),
        calm_wind_penalty=round(calm_wind_penalty, 1),
        cloud_penalty=round(cloud_penalty, 1),
        label=label,
    )
