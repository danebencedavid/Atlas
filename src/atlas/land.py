from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from atlas.anomalies import percentile_rank


SOIL_TEMPERATURE_COLUMNS = [
    "soil_temperature_0_to_7cm",
    "soil_temperature_7_to_28cm",
    "soil_temperature_28_to_100cm",
    "soil_temperature_100_to_255cm",
]

SOIL_MOISTURE_COLUMNS = [
    "soil_moisture_0_to_7cm",
    "soil_moisture_7_to_28cm",
    "soil_moisture_28_to_100cm",
    "soil_moisture_100_to_255cm",
]


@dataclass(frozen=True)
class LandSurfaceAnalysis:
    hourly: pd.DataFrame
    daily: pd.DataFrame
    metrics: dict[str, float]
    water_balance_percentiles: dict[int, float]
    moisture_context: str
    notes: list[str]


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def analyze_land_surface(
    frame: pd.DataFrame,
    standard_balance_samples: dict[int, pd.Series] | None = None,
    timezone_name: str = "Europe/Budapest",
) -> LandSurfaceAnalysis:
    if frame.empty:
        return LandSurfaceAnalysis(
            pd.DataFrame(),
            pd.DataFrame(),
            {},
            {},
            "Land-surface analysis unavailable",
            ["No land-surface time series was available."],
        )
    hourly = frame.copy().sort_values("time")
    hourly["time"] = pd.to_datetime(hourly["time"], utc=True)
    hourly["precipitation"] = _numeric(hourly, "precipitation")
    hourly["et0_fao_evapotranspiration"] = _numeric(
        hourly, "et0_fao_evapotranspiration"
    )
    hourly["water_balance_mm"] = (
        hourly["precipitation"] - hourly["et0_fao_evapotranspiration"]
    )
    for column in SOIL_TEMPERATURE_COLUMNS + SOIL_MOISTURE_COLUMNS + [
        "vapour_pressure_deficit"
    ]:
        hourly[column] = _numeric(hourly, column)

    hourly["local_time"] = hourly["time"].dt.tz_convert(timezone_name)
    daily = (
        hourly.set_index("local_time")
        .resample("1D")
        .agg(
            precipitation_mm=("precipitation", "sum"),
            et0_mm=("et0_fao_evapotranspiration", "sum"),
            water_balance_mm=("water_balance_mm", "sum"),
            vpd_mean_kpa=("vapour_pressure_deficit", "mean"),
            vpd_max_kpa=("vapour_pressure_deficit", "max"),
            soil_temperature_surface_c=("soil_temperature_0_to_7cm", "mean"),
            soil_moisture_surface=("soil_moisture_0_to_7cm", "mean"),
            soil_moisture_root_zone=("soil_moisture_28_to_100cm", "mean"),
        )
        .reset_index()
        .rename(columns={"local_time": "time"})
    )
    balances: dict[int, float] = {}
    percentiles: dict[int, float] = {}
    samples_by_window = standard_balance_samples or {}
    for days in (7, 30, 90):
        value = float(daily.tail(days)["water_balance_mm"].sum())
        balances[days] = value
        percentiles[days] = percentile_rank(value, samples_by_window.get(days, pd.Series()))

    percentile_90 = percentiles[90]
    if np.isfinite(percentile_90) and percentile_90 <= 10:
        context = "Exceptionally dry land-surface water balance"
    elif np.isfinite(percentile_90) and percentile_90 <= 25:
        context = "Sustained moisture deficit"
    elif np.isfinite(percentile_90) and percentile_90 >= 90:
        context = "Exceptionally wet land-surface water balance"
    elif np.isfinite(percentile_90) and percentile_90 >= 75:
        context = "Sustained moisture surplus"
    else:
        context = "Near-normal seasonal water balance"

    metrics = {
        "precipitation_90d_mm": float(daily.tail(90)["precipitation_mm"].sum()),
        "et0_90d_mm": float(daily.tail(90)["et0_mm"].sum()),
        "water_balance_7d_mm": balances[7],
        "water_balance_30d_mm": balances[30],
        "water_balance_90d_mm": balances[90],
        "vpd_max_kpa": float(hourly["vapour_pressure_deficit"].max()),
        "soil_temperature_surface_c": float(hourly["soil_temperature_0_to_7cm"].iloc[-1]),
        "soil_moisture_surface": float(hourly["soil_moisture_0_to_7cm"].iloc[-1]),
        "soil_moisture_root_zone": float(hourly["soil_moisture_28_to_100cm"].iloc[-1]),
    }
    notes = [
        "Rolling soil, VPD and ET0 fields use Open-Meteo Historical Weather best-match gridded data, not station measurements.",
        "The 1991-2020 water-balance reference is fixed to ERA5; the rolling best-match series can use newer IFS and ERA5/ERA5-Land inputs.",
        "Water balance is precipitation minus FAO-56 reference evapotranspiration and does not include runoff or irrigation.",
        "Dry/wet context uses the 1991-2020 distribution of same-calendar water-balance windows.",
    ]
    return LandSurfaceAnalysis(hourly, daily, metrics, percentiles, context, notes)
