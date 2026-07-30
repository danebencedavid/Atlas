from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path

import numpy as np
import pandas as pd

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


def _cache_path(config: AtlasConfig, valid_date: date, data_dir: Path) -> Path:
    slug = config.location.name.lower().replace(" ", "_")
    return data_dir / "raw" / f"open_meteo_model_profile_{slug}_{valid_date.isoformat()}.json"


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


def _diagnostics(frame: pd.DataFrame) -> dict[str, float]:
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

    return {
        "k_index": float(k_index),
        "total_totals_index": float(total_totals),
        "lapse_rate_850_500_c_km": float(lapse),
        "freezing_level_m_asl": freezing_level,
    }


def fetch_model_profile(
    config: AtlasConfig,
    valid_date: date,
    data_dir: Path | None = None,
    refresh: bool = False,
) -> ModelProfile:
    if not config.profile.enabled:
        return ModelProfile(pd.DataFrame(), None, "Open-Meteo", {}, ["Model profile ingestion is disabled."])

    data_dir = data_dir or config.outputs.data_dir
    cache_file = _cache_path(config, valid_date, data_dir)
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

    try:
        if cache_file.exists() and not refresh:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            payload = fetch_json_with_retry(
                HISTORICAL_FORECAST_URL,
                {
                    "latitude": config.location.latitude,
                    "longitude": config.location.longitude,
                    "start_date": valid_date.isoformat(),
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
        for level in config.profile.pressure_levels_hpa:
            temperature_c = _value(payload, f"temperature_{level}hPa", selected_index)
            relative_humidity_pct = _value(payload, f"relative_humidity_{level}hPa", selected_index)
            rows.append(
                {
                    "pressure_hpa": float(level),
                    "temperature_c": temperature_c,
                    "relative_humidity_pct": relative_humidity_pct,
                    "dew_point_c": _dew_point_c(temperature_c, relative_humidity_pct),
                    "wind_speed_ms": _value(payload, f"wind_speed_{level}hPa", selected_index),
                    "wind_direction_deg": _value(payload, f"wind_direction_{level}hPa", selected_index),
                    "geopotential_height_m": _value(
                        payload, f"geopotential_height_{level}hPa", selected_index
                    ),
                }
            )
        frame = pd.DataFrame(rows).dropna(subset=["temperature_c", "pressure_hpa"])
        if len(frame) < 5:
            raise ValueError(f"Only {len(frame)} usable pressure levels were returned.")
        return ModelProfile(
            frame=frame,
            valid_time=valid_time,
            source="Open-Meteo Historical Forecast pressure levels",
            diagnostics=_diagnostics(frame),
            notes=[
                "Model-derived atmospheric profile near Debrecen; it is not an observed radiosonde.",
                "Dew point is calculated from model temperature and relative humidity.",
            ],
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
