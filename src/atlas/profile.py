from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from metpy import calc as mpcalc
from metpy.units import units

from atlas.config import AtlasConfig
from atlas.ingest import fetch_json_with_retry


HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class ModelProfile:
    frame: pd.DataFrame
    valid_time: pd.Timestamp | None
    source: str
    diagnostics: dict[str, float]
    notes: list[str]
    series: pd.DataFrame = field(default_factory=pd.DataFrame)
    surface_series: pd.DataFrame = field(default_factory=pd.DataFrame)


def _cache_path(config: AtlasConfig, start_date: date, valid_date: date, data_dir: Path) -> Path:
    slug = config.location.name.lower().replace(" ", "_")
    return (
        data_dir
        / "raw"
        / f"open_meteo_model_profile_{slug}_{start_date.isoformat()}_{valid_date.isoformat()}.json"
    )


def _dew_point_c(temperature_c: float, relative_humidity_pct: float) -> float:
    if not np.isfinite(temperature_c) or not np.isfinite(relative_humidity_pct):
        return float("nan")
    rh = min(max(relative_humidity_pct, 0.1), 100.0)
    gamma = math.log(rh / 100.0) + 17.625 * temperature_c / (243.04 + temperature_c)
    return 243.04 * gamma / (17.625 - gamma)


def _value(payload: dict, variable: str, index: int) -> float:
    values = payload.get("hourly", {}).get(variable, [])
    if index >= len(values) or values[index] is None:
        return float("nan")
    return float(values[index])


def _height_at_pressure(frame: pd.DataFrame, pressure_hpa: float) -> float:
    usable = frame.dropna(subset=["pressure_hpa", "geopotential_height_m"]).sort_values("pressure_hpa")
    if usable.empty or not np.isfinite(pressure_hpa):
        return float("nan")
    if pressure_hpa < usable["pressure_hpa"].min() or pressure_hpa > usable["pressure_hpa"].max():
        return float("nan")
    return float(
        np.interp(
            pressure_hpa,
            usable["pressure_hpa"].to_numpy(dtype=float),
            usable["geopotential_height_m"].to_numpy(dtype=float),
        )
    )


def _parcel_diagnostics(frame: pd.DataFrame) -> dict[str, float]:
    ordered = frame.dropna(subset=["pressure_hpa", "temperature_c", "dew_point_c"]).sort_values(
        "pressure_hpa", ascending=False
    )
    if len(ordered) < 5:
        return {}
    try:
        pressure = ordered["pressure_hpa"].to_numpy(dtype=float) * units.hPa
        temperature = ordered["temperature_c"].to_numpy(dtype=float) * units.degC
        dewpoint = ordered["dew_point_c"].to_numpy(dtype=float) * units.degC
        parcel = mpcalc.parcel_profile(pressure, temperature[0], dewpoint[0])
        cape, cin = mpcalc.cape_cin(pressure, temperature, dewpoint, parcel)
        lcl_pressure, _ = mpcalc.lcl(pressure[0], temperature[0], dewpoint[0])
        lfc_pressure, _ = mpcalc.lfc(
            pressure, temperature, dewpoint, parcel_temperature_profile=parcel
        )
        el_pressure, _ = mpcalc.el(
            pressure, temperature, dewpoint, parcel_temperature_profile=parcel
        )
        precipitable_water = mpcalc.precipitable_water(pressure, dewpoint)
        wet_bulb = mpcalc.wet_bulb_temperature(pressure, temperature, dewpoint).to("degC").m
        wet_bulb_zero = float("nan")
        heights = ordered["geopotential_height_m"].to_numpy(dtype=float)
        for lower_index in range(len(wet_bulb) - 1):
            lower_value = float(wet_bulb[lower_index])
            upper_value = float(wet_bulb[lower_index + 1])
            if lower_value >= 0 > upper_value:
                fraction = lower_value / (lower_value - upper_value)
                wet_bulb_zero = float(
                    heights[lower_index]
                    + fraction * (heights[lower_index + 1] - heights[lower_index])
                )
                break
        lcl_hpa = float(lcl_pressure.to("hPa").m)
        lfc_hpa = float(lfc_pressure.to("hPa").m) if np.isfinite(lfc_pressure.m) else float("nan")
        el_hpa = float(el_pressure.to("hPa").m) if np.isfinite(el_pressure.m) else float("nan")
        return {
            "surface_based_cape_j_kg": float(cape.to("joule / kilogram").m),
            "surface_based_cin_j_kg": float(cin.to("joule / kilogram").m),
            "lcl_pressure_hpa": lcl_hpa,
            "lcl_height_m_asl": _height_at_pressure(ordered, lcl_hpa),
            "lfc_pressure_hpa": lfc_hpa,
            "lfc_height_m_asl": _height_at_pressure(ordered, lfc_hpa),
            "equilibrium_level_pressure_hpa": el_hpa,
            "equilibrium_level_height_m_asl": _height_at_pressure(ordered, el_hpa),
            "precipitable_water_mm": float(precipitable_water.to("millimeter").m),
            "wet_bulb_zero_m_asl": wet_bulb_zero,
        }
    except Exception:
        return {}


def _diagnostics(frame: pd.DataFrame, surface: pd.Series | None = None) -> dict[str, float]:
    by_level = frame.set_index("pressure_hpa")

    def value(level: int, column: str) -> float:
        if level not in by_level.index:
            return float("nan")
        return float(by_level.loc[level, column])

    t850 = value(850, "temperature_c")
    td850 = value(850, "dew_point_c")
    t700 = value(700, "temperature_c")
    td700 = value(700, "dew_point_c")
    t500 = value(500, "temperature_c")
    z850 = value(850, "geopotential_height_m")
    z500 = value(500, "geopotential_height_m")

    lapse = float("nan")
    if all(np.isfinite(item) for item in [t850, t500, z850, z500]) and z500 > z850:
        lapse = (t850 - t500) / ((z500 - z850) / 1000.0)

    k_index = t850 - t500 + td850 - (t700 - td700)
    total_totals = t850 + td850 - 2 * t500

    freezing_level = float("nan")
    ordered = frame.sort_values("geopotential_height_m")
    for (_, lower), (_, upper) in zip(ordered.iloc[:-1].iterrows(), ordered.iloc[1:].iterrows()):
        lower_t = float(lower["temperature_c"])
        upper_t = float(upper["temperature_c"])
        if np.isfinite(lower_t) and np.isfinite(upper_t) and lower_t >= 0 > upper_t:
            fraction = lower_t / (lower_t - upper_t)
            freezing_level = float(
                lower["geopotential_height_m"]
                + fraction * (upper["geopotential_height_m"] - lower["geopotential_height_m"])
            )
            break

    diagnostics = {
        "k_index": float(k_index),
        "total_totals_index": float(total_totals),
        "lapse_rate_850_500_c_km": float(lapse),
        "freezing_level_m_asl": freezing_level,
    }
    diagnostics.update(_parcel_diagnostics(frame))
    if surface is not None:
        for source, target in {
            "cape": "model_cape_j_kg",
            "convective_inhibition": "model_cin_j_kg",
            "freezing_level_height": "model_freezing_level_m_asl",
            "boundary_layer_height": "boundary_layer_height_m",
            "total_column_integrated_water_vapour": "model_column_water_kg_m2",
            "wet_bulb_temperature_2m": "wet_bulb_temperature_2m_c",
        }.items():
            value = pd.to_numeric(surface.get(source), errors="coerce")
            diagnostics[target] = float(value) if pd.notna(value) else float("nan")
        boundary_height = diagnostics.get("boundary_layer_height_m", float("nan"))
        low_level = frame[
            frame["geopotential_height_m"]
            <= frame["geopotential_height_m"].min() + max(boundary_height, 500.0)
        ]
        mean_wind = pd.to_numeric(low_level["wind_speed_ms"], errors="coerce").mean()
        diagnostics["ventilation_index_m2_s"] = (
            float(boundary_height * mean_wind)
            if np.isfinite(boundary_height) and np.isfinite(mean_wind)
            else float("nan")
        )
    return diagnostics


def fetch_model_profile(
    config: AtlasConfig,
    valid_date: date,
    start_date: date | None = None,
    data_dir: Path | None = None,
    refresh: bool = False,
) -> ModelProfile:
    if not config.profile.enabled:
        return ModelProfile(pd.DataFrame(), None, "Open-Meteo", {}, ["Model profile ingestion is disabled."])

    data_dir = data_dir or config.outputs.data_dir
    start_date = start_date or valid_date
    cache_file = _cache_path(config, start_date, valid_date, data_dir)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    variables: list[str] = []
    for level in config.profile.pressure_levels_hpa:
        variables.extend(
            [
                f"temperature_{level}hPa",
                f"relative_humidity_{level}hPa",
                f"wind_speed_{level}hPa",
                f"wind_direction_{level}hPa",
                f"geopotential_height_{level}hPa",
            ]
        )
    surface_variables = [
        "cape",
        "convective_inhibition",
        "freezing_level_height",
        "boundary_layer_height",
        "total_column_integrated_water_vapour",
        "wet_bulb_temperature_2m",
    ]
    variables.extend(surface_variables)

    try:
        if cache_file.exists() and not refresh:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            payload = fetch_json_with_retry(
                HISTORICAL_FORECAST_URL,
                {
                    "latitude": config.location.latitude,
                    "longitude": config.location.longitude,
                    "start_date": start_date.isoformat(),
                    "end_date": valid_date.isoformat(),
                    "hourly": ",".join(variables),
                    "timezone": "UTC",
                    "wind_speed_unit": "ms",
                },
            )
            cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        hourly = payload.get("hourly", {})
        timestamps = pd.to_datetime(hourly.get("time", []), utc=True)
        if timestamps.empty:
            raise ValueError("No pressure-level timestamps were returned.")
        target = pd.Timestamp(
            datetime.combine(valid_date, time(config.profile.target_hour_utc), tzinfo=timezone.utc)
        )
        selected_index = int(np.argmin(np.abs(timestamps - target)))
        valid_time = timestamps[selected_index]

        rows = []
        for time_index, timestamp in enumerate(timestamps):
            for level in config.profile.pressure_levels_hpa:
                temperature_c = _value(payload, f"temperature_{level}hPa", time_index)
                relative_humidity_pct = _value(
                    payload, f"relative_humidity_{level}hPa", time_index
                )
                rows.append(
                    {
                        "time": timestamp,
                        "pressure_hpa": float(level),
                        "temperature_c": temperature_c,
                        "relative_humidity_pct": relative_humidity_pct,
                        "dew_point_c": _dew_point_c(temperature_c, relative_humidity_pct),
                        "wind_speed_ms": _value(
                            payload, f"wind_speed_{level}hPa", time_index
                        ),
                        "wind_direction_deg": _value(
                            payload, f"wind_direction_{level}hPa", time_index
                        ),
                        "geopotential_height_m": _value(
                            payload, f"geopotential_height_{level}hPa", time_index
                        ),
                    }
                )
        series = pd.DataFrame(rows).dropna(subset=["temperature_c", "pressure_hpa"])
        surface_series = pd.DataFrame(
            {
                "time": timestamps,
                **{
                    variable: [
                        _value(payload, variable, time_index)
                        for time_index in range(len(timestamps))
                    ]
                    for variable in surface_variables
                },
            }
        )
        frame = series[series["time"] == valid_time].copy()
        if len(frame) < 5:
            raise ValueError(f"Only {len(frame)} usable pressure levels were returned.")
        surface = surface_series[surface_series["time"] == valid_time]
        selected_surface = surface.iloc[0] if not surface.empty else None
        return ModelProfile(
            frame=frame,
            valid_time=valid_time,
            source="Open-Meteo Historical Forecast pressure levels",
            diagnostics=_diagnostics(frame, selected_surface),
            notes=[
                "Model-derived atmospheric profile near Debrecen; it is not an observed radiosonde.",
                "Dew point is calculated from model temperature and relative humidity.",
            ],
            series=series,
            surface_series=surface_series,
        )
    except Exception as exc:
        if config.profile.required:
            raise RuntimeError(f"Required model profile was unavailable: {exc}") from exc
        return ModelProfile(
            pd.DataFrame(),
            None,
            "Open-Meteo Historical Forecast pressure levels",
            {},
            [f"Model profile was unavailable: {exc}"],
        )
