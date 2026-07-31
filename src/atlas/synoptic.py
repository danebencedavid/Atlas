from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.config import AtlasConfig
from atlas.ingest import fetch_json_with_retry
from atlas.profile import HISTORICAL_FORECAST_URL


SYNOPTIC_VARIABLES = [
    "pressure_msl",
    "geopotential_height_500hPa",
    "temperature_850hPa",
    "wind_speed_850hPa",
    "wind_direction_850hPa",
]


@dataclass(frozen=True)
class SynopticArchive:
    times: list[pd.Timestamp]
    latitudes: np.ndarray
    longitudes: np.ndarray
    pressure_msl_hpa: np.ndarray
    height_500m: np.ndarray
    temperature_850c: np.ndarray
    wind_u_850ms: np.ndarray
    wind_v_850ms: np.ndarray
    notes: list[str]


def _empty(notes: list[str]) -> SynopticArchive:
    return SynopticArchive(
        [], np.array([]), np.array([]), np.empty((0, 0, 0)), np.empty((0, 0, 0)),
        np.empty((0, 0, 0)), np.empty((0, 0, 0)), np.empty((0, 0, 0)), notes
    )


def _cache_path(config: AtlasConfig, start: date, end: date) -> Path:
    return config.outputs.data_dir / "raw" / f"open_meteo_synoptic_{start.isoformat()}_{end.isoformat()}.json"


def fetch_synoptic_archive(
    config: AtlasConfig,
    start: date,
    end: date,
    refresh: bool = False,
) -> SynopticArchive:
    if not config.synoptic.enabled:
        return _empty(["Synoptic-grid ingestion is disabled."])
    cache = _cache_path(config, start, end)
    latitudes = np.arange(
        config.synoptic.latitude_min,
        config.synoptic.latitude_max + config.synoptic.grid_step_degrees / 2.0,
        config.synoptic.grid_step_degrees,
    )
    longitudes = np.arange(
        config.synoptic.longitude_min,
        config.synoptic.longitude_max + config.synoptic.grid_step_degrees / 2.0,
        config.synoptic.grid_step_degrees,
    )
    requested_latitudes = np.repeat(latitudes, len(longitudes))
    requested_longitudes = np.tile(longitudes, len(latitudes))
    try:
        if cache.exists() and not refresh:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        else:
            payload = fetch_json_with_retry(
                HISTORICAL_FORECAST_URL,
                {
                    "latitude": ",".join(f"{value:.3f}" for value in requested_latitudes),
                    "longitude": ",".join(f"{value:.3f}" for value in requested_longitudes),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "hourly": ",".join(SYNOPTIC_VARIABLES),
                    "timezone": "UTC",
                    "wind_speed_unit": "ms",
                },
            )
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        locations = payload if isinstance(payload, list) else [payload]
        if len(locations) != len(requested_latitudes):
            raise ValueError(
                f"Expected {len(requested_latitudes)} synoptic grid points, received {len(locations)}."
            )
        all_times = pd.to_datetime(locations[0].get("hourly", {}).get("time", []), utc=True)
        selected_indices = [
            index
            for index, timestamp in enumerate(all_times)
            if timestamp.hour % config.synoptic.frame_interval_hours == 0
        ]
        if not selected_indices:
            raise ValueError("No synoptic timestamps matched the configured frame interval.")
        shape = (len(selected_indices), len(latitudes), len(longitudes))
        fields = {
            variable: np.full(shape, np.nan, dtype=float) for variable in SYNOPTIC_VARIABLES
        }
        for point_index, location in enumerate(locations):
            lat_index = point_index // len(longitudes)
            lon_index = point_index % len(longitudes)
            hourly = location.get("hourly", {})
            for variable in SYNOPTIC_VARIABLES:
                values = pd.to_numeric(pd.Series(hourly.get(variable, [])), errors="coerce").to_numpy()
                if len(values) <= max(selected_indices):
                    continue
                fields[variable][:, lat_index, lon_index] = values[selected_indices]
        direction = np.radians(fields["wind_direction_850hPa"])
        speed = fields["wind_speed_850hPa"]
        wind_u = -speed * np.sin(direction)
        wind_v = -speed * np.cos(direction)
        return SynopticArchive(
            times=[all_times[index] for index in selected_indices],
            latitudes=latitudes,
            longitudes=longitudes,
            pressure_msl_hpa=fields["pressure_msl"],
            height_500m=fields["geopotential_height_500hPa"],
            temperature_850c=fields["temperature_850hPa"],
            wind_u_850ms=wind_u,
            wind_v_850ms=wind_v,
            notes=[
                "Synoptic fields are model analyses from Open-Meteo Historical Forecast data.",
                f"Frames are sampled every {config.synoptic.frame_interval_hours} hours on a {config.synoptic.grid_step_degrees:g}-degree Central European grid.",
            ],
        )
    except Exception as exc:
        if config.synoptic.required:
            raise RuntimeError(f"Required synoptic archive was unavailable: {exc}") from exc
        return _empty([f"Synoptic archive unavailable: {exc}"])
