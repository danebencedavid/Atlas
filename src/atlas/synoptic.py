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
    "geopotential_height_300hPa",
    "temperature_850hPa",
    "relative_humidity_850hPa",
    "wind_speed_850hPa",
    "wind_direction_850hPa",
    "wind_speed_500hPa",
    "wind_direction_500hPa",
    "wind_speed_300hPa",
    "wind_direction_300hPa",
    "relative_humidity_700hPa",
    "vertical_velocity_700hPa",
]


@dataclass(frozen=True)
class SynopticArchive:
    times: list[pd.Timestamp]
    latitudes: np.ndarray
    longitudes: np.ndarray
    pressure_msl_hpa: np.ndarray
    height_500m: np.ndarray
    height_300m: np.ndarray
    temperature_850c: np.ndarray
    wind_u_850ms: np.ndarray
    wind_v_850ms: np.ndarray
    wind_speed_300ms: np.ndarray
    vorticity_500_1e5_s: np.ndarray
    relative_humidity_700pct: np.ndarray
    vertical_velocity_700ms: np.ndarray
    theta_e_850k: np.ndarray
    temperature_advection_850c_3h: np.ndarray
    frontogenesis_850k_100km_3h: np.ndarray
    notes: list[str]


def _empty(notes: list[str]) -> SynopticArchive:
    return SynopticArchive(
        times=[],
        latitudes=np.array([]),
        longitudes=np.array([]),
        pressure_msl_hpa=np.empty((0, 0, 0)),
        height_500m=np.empty((0, 0, 0)),
        height_300m=np.empty((0, 0, 0)),
        temperature_850c=np.empty((0, 0, 0)),
        wind_u_850ms=np.empty((0, 0, 0)),
        wind_v_850ms=np.empty((0, 0, 0)),
        wind_speed_300ms=np.empty((0, 0, 0)),
        vorticity_500_1e5_s=np.empty((0, 0, 0)),
        relative_humidity_700pct=np.empty((0, 0, 0)),
        vertical_velocity_700ms=np.empty((0, 0, 0)),
        theta_e_850k=np.empty((0, 0, 0)),
        temperature_advection_850c_3h=np.empty((0, 0, 0)),
        frontogenesis_850k_100km_3h=np.empty((0, 0, 0)),
        notes=notes,
    )


def _wind_components(speed: np.ndarray, direction_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    direction = np.radians(direction_deg)
    return -speed * np.sin(direction), -speed * np.cos(direction)


def _horizontal_derivatives(
    field: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    earth_radius_m = 6_371_000.0
    latitude_radians = np.radians(latitudes)
    longitude_radians = np.radians(longitudes)
    d_dlat = np.gradient(field, latitude_radians, axis=1, edge_order=1) / earth_radius_m
    d_dlon = np.gradient(field, longitude_radians, axis=2, edge_order=1)
    cos_latitude = np.cos(latitude_radians)[None, :, None]
    d_dx = d_dlon / (earth_radius_m * np.maximum(cos_latitude, 0.05))
    return d_dx, d_dlat


def _derived_dynamics(
    fields: dict[str, np.ndarray],
    latitudes: np.ndarray,
    longitudes: np.ndarray,
) -> dict[str, np.ndarray]:
    wind_u_500, wind_v_500 = _wind_components(
        fields["wind_speed_500hPa"], fields["wind_direction_500hPa"]
    )
    dv_dx, _ = _horizontal_derivatives(wind_v_500, latitudes, longitudes)
    _, du_dy = _horizontal_derivatives(wind_u_500, latitudes, longitudes)
    vorticity = (dv_dx - du_dy) * 100_000.0

    wind_u_850, wind_v_850 = _wind_components(
        fields["wind_speed_850hPa"], fields["wind_direction_850hPa"]
    )
    temperature_k = fields["temperature_850hPa"] + 273.15
    temp_dx, temp_dy = _horizontal_derivatives(temperature_k, latitudes, longitudes)
    temperature_advection = -(wind_u_850 * temp_dx + wind_v_850 * temp_dy) * 10_800.0
    du_dx, du_dy = _horizontal_derivatives(wind_u_850, latitudes, longitudes)
    dv_dx, dv_dy = _horizontal_derivatives(wind_v_850, latitudes, longitudes)
    gradient = np.hypot(temp_dx, temp_dy)
    orientation = np.arctan2(temp_dy, temp_dx)
    stretching = du_dx - dv_dy
    shearing = dv_dx + du_dy
    divergence = du_dx + dv_dy
    frontogenesis = (
        0.5
        * gradient
        * (
            stretching * np.cos(2.0 * orientation)
            + shearing * np.sin(2.0 * orientation)
            - divergence
        )
        * 100_000.0
        * 10_800.0
    )

    relative_humidity = np.clip(fields["relative_humidity_850hPa"], 1.0, 100.0)
    temperature_c = fields["temperature_850hPa"]
    gamma = np.log(relative_humidity / 100.0) + 17.625 * temperature_c / (243.04 + temperature_c)
    dewpoint_c = 243.04 * gamma / (17.625 - gamma)
    pressure_hpa = 850.0
    theta = temperature_k * (1000.0 / pressure_hpa) ** 0.2854
    mixing_ratio = 0.622 * (
        6.112 * np.exp(17.67 * dewpoint_c / (dewpoint_c + 243.5))
    ) / np.maximum(
        pressure_hpa - 6.112 * np.exp(17.67 * dewpoint_c / (dewpoint_c + 243.5)),
        1.0,
    )
    theta_e = theta * np.exp((2_500_000.0 * mixing_ratio) / (1004.0 * temperature_k))
    return {
        "wind_u_850": wind_u_850,
        "wind_v_850": wind_v_850,
        "vorticity_500": vorticity,
        "temperature_advection_850": temperature_advection,
        "frontogenesis_850": frontogenesis,
        "theta_e_850": theta_e,
    }


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
        derived = _derived_dynamics(fields, latitudes, longitudes)
        return SynopticArchive(
            times=[all_times[index] for index in selected_indices],
            latitudes=latitudes,
            longitudes=longitudes,
            pressure_msl_hpa=fields["pressure_msl"],
            height_500m=fields["geopotential_height_500hPa"],
            height_300m=fields["geopotential_height_300hPa"],
            temperature_850c=fields["temperature_850hPa"],
            wind_u_850ms=derived["wind_u_850"],
            wind_v_850ms=derived["wind_v_850"],
            wind_speed_300ms=fields["wind_speed_300hPa"],
            vorticity_500_1e5_s=derived["vorticity_500"],
            relative_humidity_700pct=fields["relative_humidity_700hPa"],
            vertical_velocity_700ms=fields["vertical_velocity_700hPa"],
            theta_e_850k=derived["theta_e_850"],
            temperature_advection_850c_3h=derived["temperature_advection_850"],
            frontogenesis_850k_100km_3h=derived["frontogenesis_850"],
            notes=[
                "Synoptic fields are model analyses from Open-Meteo Historical Forecast data.",
                f"Frames are sampled every {config.synoptic.frame_interval_hours} hours on a {config.synoptic.grid_step_degrees:g}-degree Central European grid.",
                "Vorticity, thermal advection and kinematic frontogenesis are finite-difference diagnostics derived on the reporting grid.",
                "A true 2-PVU dynamical-tropopause surface is not exposed by the no-secret provider and is not approximated.",
            ],
        )
    except Exception as exc:
        if config.synoptic.required:
            raise RuntimeError(f"Required synoptic archive was unavailable: {exc}") from exc
        return _empty([f"Synoptic archive unavailable: {exc}"])
