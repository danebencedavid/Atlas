"""Back-trajectories that answer where the air over Debrecen came from.

The rest of the analysis describes the air mass once it has arrived. This traces
it backwards through the reanalysis wind field at a single pressure level, which
is what turns "warm and dry" into "warm and dry because it subsided over the
Balkans two days ago".

Integration is a midpoint (RK2) step through a wind field interpolated
bilinearly in space and linearly in time. That is a kinematic trajectory: it
follows the horizontal wind at one level and does not track vertical motion, so
it is a guide to origin rather than a parcel history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.config import AtlasConfig
from atlas.ingest import fetch_json_with_retry

HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

EARTH_RADIUS_KM = 6371.0088
METRES_PER_DEGREE_LATITUDE = 111_320.0

COMPASS_SECTORS = [
    "north", "north-north-east", "north-east", "east-north-east",
    "east", "east-south-east", "south-east", "south-south-east",
    "south", "south-south-west", "south-west", "west-south-west",
    "west", "west-north-west", "north-west", "north-north-west",
]


@dataclass(frozen=True)
class TrajectoryField:
    """Wind and temperature on a coarse grid, ordered by ascending coordinate."""

    times: list[pd.Timestamp]
    latitudes: np.ndarray
    longitudes: np.ndarray
    wind_u_ms: np.ndarray
    wind_v_ms: np.ndarray
    temperature_c: np.ndarray
    level_hpa: int
    notes: list[str]

    @property
    def available(self) -> bool:
        return bool(self.times) and self.wind_u_ms.size > 0


@dataclass(frozen=True)
class TrajectoryPoint:
    time: str
    hours_before_arrival: float
    latitude: float
    longitude: float
    distance_from_city_km: float
    temperature_c: float


@dataclass(frozen=True)
class AirMassOrigin:
    level_hpa: int
    hours_traced: float
    hours_requested: int
    points: list[TrajectoryPoint]
    origin_sector: str
    origin_distance_km: float
    path_length_km: float
    mean_speed_ms: float
    temperature_change_c: float
    left_domain: bool
    notes: list[str]

    @property
    def available(self) -> bool:
        return len(self.points) > 1

    @property
    def summary(self) -> str:
        if not self.available:
            return "The air mass could not be traced backwards through the wind field."
        travelled = (
            f"{self.origin_distance_km:,.0f} km from the {self.origin_sector}"
            if self.origin_distance_km >= 1.0
            else "barely at all, leaving the air effectively stationary"
        )
        trend = (
            "warming"
            if self.temperature_change_c > 0.5
            else "cooling"
            if self.temperature_change_c < -0.5
            else "holding its temperature"
        )
        return (
            f"Over the previous {self.hours_traced:.0f} hours the air arriving at "
            f"{self.level_hpa} hPa travelled {travelled}, "
            f"{trend} by {abs(self.temperature_change_c):.1f} °C along the way."
        )


def _empty_origin(config: AtlasConfig, notes: list[str]) -> AirMassOrigin:
    return AirMassOrigin(
        level_hpa=config.trajectory.level_hpa,
        hours_traced=0.0,
        hours_requested=config.trajectory.hours,
        points=[],
        origin_sector="unknown",
        origin_distance_km=0.0,
        path_length_km=0.0,
        mean_speed_ms=0.0,
        temperature_change_c=0.0,
        left_domain=False,
        notes=notes,
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = np.radians(lon2 - lon1)
    a = np.sin(delta_phi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(delta_lambda / 2) ** 2
    return float(2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a)))


def _bearing_deg(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> float:
    phi1, phi2 = np.radians(from_lat), np.radians(to_lat)
    delta_lambda = np.radians(to_lon - from_lon)
    y = np.sin(delta_lambda) * np.cos(phi2)
    x = np.cos(phi1) * np.sin(phi2) - np.sin(phi1) * np.cos(phi2) * np.cos(delta_lambda)
    return float((np.degrees(np.arctan2(y, x)) + 360.0) % 360.0)


def _sector(bearing_deg: float) -> str:
    index = int((bearing_deg + 11.25) % 360.0 // 22.5)
    return COMPASS_SECTORS[index]


def _interpolate(
    field: np.ndarray,
    times_seconds: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    when: float,
    latitude: float,
    longitude: float,
) -> float:
    """Bilinear in space, linear in time. Returns NaN outside the domain."""
    if not (latitudes[0] <= latitude <= latitudes[-1] and longitudes[0] <= longitude <= longitudes[-1]):
        return float("nan")
    when = float(np.clip(when, times_seconds[0], times_seconds[-1]))
    time_index = int(np.clip(np.searchsorted(times_seconds, when) - 1, 0, len(times_seconds) - 2))
    lat_index = int(np.clip(np.searchsorted(latitudes, latitude) - 1, 0, len(latitudes) - 2))
    lon_index = int(np.clip(np.searchsorted(longitudes, longitude) - 1, 0, len(longitudes) - 2))

    time_span = times_seconds[time_index + 1] - times_seconds[time_index]
    lat_span = latitudes[lat_index + 1] - latitudes[lat_index]
    lon_span = longitudes[lon_index + 1] - longitudes[lon_index]
    time_weight = 0.0 if time_span == 0 else (when - times_seconds[time_index]) / time_span
    lat_weight = 0.0 if lat_span == 0 else (latitude - latitudes[lat_index]) / lat_span
    lon_weight = 0.0 if lon_span == 0 else (longitude - longitudes[lon_index]) / lon_span

    total = 0.0
    for time_offset, time_factor in ((0, 1 - time_weight), (1, time_weight)):
        if time_factor == 0:
            continue
        for lat_offset, lat_factor in ((0, 1 - lat_weight), (1, lat_weight)):
            if lat_factor == 0:
                continue
            for lon_offset, lon_factor in ((0, 1 - lon_weight), (1, lon_weight)):
                if lon_factor == 0:
                    continue
                corner = field[time_index + time_offset, lat_index + lat_offset, lon_index + lon_offset]
                if not np.isfinite(corner):
                    return float("nan")
                total += corner * time_factor * lat_factor * lon_factor
    return float(total)


def compute_air_mass_origin(
    field: TrajectoryField,
    config: AtlasConfig,
    step_minutes: int = 15,
) -> AirMassOrigin:
    """Trace the air arriving over the city backwards through the wind field."""
    if not field.available or len(field.times) < 2:
        return _empty_origin(config, ["No wind field was available for a back-trajectory."])

    times_seconds = np.array([timestamp.timestamp() for timestamp in field.times], dtype=float)
    arrival = times_seconds[-1]
    latitude = float(config.location.latitude)
    longitude = float(config.location.longitude)
    step = float(step_minutes) * 60.0
    total_steps = int(config.trajectory.hours * 3600 // step)

    def wind(when: float, lat: float, lon: float) -> tuple[float, float]:
        u = _interpolate(field.wind_u_ms, times_seconds, field.latitudes, field.longitudes, when, lat, lon)
        v = _interpolate(field.wind_v_ms, times_seconds, field.latitudes, field.longitudes, when, lat, lon)
        return u, v

    def as_degrees(u: float, v: float, lat: float, seconds: float) -> tuple[float, float]:
        d_lat = v * seconds / METRES_PER_DEGREE_LATITUDE
        scale = np.cos(np.radians(np.clip(lat, -89.0, 89.0)))
        d_lon = 0.0 if scale <= 1e-6 else u * seconds / (METRES_PER_DEGREE_LATITUDE * scale)
        return d_lat, d_lon

    points: list[TrajectoryPoint] = []
    temperature = _interpolate(
        field.temperature_c, times_seconds, field.latitudes, field.longitudes, arrival, latitude, longitude
    )
    points.append(
        TrajectoryPoint(
            time=field.times[-1].isoformat(),
            hours_before_arrival=0.0,
            latitude=latitude,
            longitude=longitude,
            distance_from_city_km=0.0,
            temperature_c=temperature,
        )
    )

    path_length_km = 0.0
    left_domain = False
    when = arrival
    for index in range(total_steps):
        u, v = wind(when, latitude, longitude)
        if not (np.isfinite(u) and np.isfinite(v)):
            left_domain = True
            break
        # Midpoint step: evaluate the wind half a step back, then apply it fully.
        half_lat, half_lon = as_degrees(u, v, latitude, -step / 2.0)
        mid_u, mid_v = wind(when - step / 2.0, latitude + half_lat, longitude + half_lon)
        if not (np.isfinite(mid_u) and np.isfinite(mid_v)):
            left_domain = True
            break
        d_lat, d_lon = as_degrees(mid_u, mid_v, latitude + half_lat, -step)
        next_latitude = latitude + d_lat
        next_longitude = longitude + d_lon
        if not (
            field.latitudes[0] <= next_latitude <= field.latitudes[-1]
            and field.longitudes[0] <= next_longitude <= field.longitudes[-1]
        ):
            left_domain = True
            break

        path_length_km += _haversine_km(latitude, longitude, next_latitude, next_longitude)
        latitude, longitude = next_latitude, next_longitude
        when -= step

        elapsed_hours = (arrival - when) / 3600.0
        if (index + 1) % max(1, int(3600 // step)) == 0:
            points.append(
                TrajectoryPoint(
                    time=pd.Timestamp(when, unit="s", tz="UTC").isoformat(),
                    hours_before_arrival=elapsed_hours,
                    latitude=latitude,
                    longitude=longitude,
                    distance_from_city_km=_haversine_km(
                        config.location.latitude, config.location.longitude, latitude, longitude
                    ),
                    temperature_c=_interpolate(
                        field.temperature_c,
                        times_seconds,
                        field.latitudes,
                        field.longitudes,
                        when,
                        latitude,
                        longitude,
                    ),
                )
            )

    notes = list(field.notes)
    notes.append(
        "A kinematic trajectory at one pressure level: it follows the horizontal wind "
        "and does not track vertical motion, so it indicates origin rather than parcel history."
    )
    if left_domain:
        notes.append(
            "The trajectory reached the edge of the wind domain and stops there rather "
            "than continuing on extrapolated wind."
        )
    if len(points) < 2:
        return _empty_origin(config, notes)

    origin = points[-1]
    hours_traced = origin.hours_before_arrival
    bearing = _bearing_deg(
        config.location.latitude, config.location.longitude, origin.latitude, origin.longitude
    )
    mean_speed = (path_length_km * 1000.0 / (hours_traced * 3600.0)) if hours_traced > 0 else 0.0
    start_temperature = origin.temperature_c
    end_temperature = points[0].temperature_c
    change = (
        float(end_temperature - start_temperature)
        if np.isfinite(start_temperature) and np.isfinite(end_temperature)
        else 0.0
    )
    return AirMassOrigin(
        level_hpa=field.level_hpa,
        hours_traced=hours_traced,
        hours_requested=config.trajectory.hours,
        points=points,
        origin_sector=_sector(bearing),
        origin_distance_km=origin.distance_from_city_km,
        path_length_km=path_length_km,
        mean_speed_ms=mean_speed,
        temperature_change_c=change,
        left_domain=left_domain,
        notes=notes,
    )


def _cache_path(config: AtlasConfig, start: date, end: date) -> Path:
    return config.outputs.data_dir / "raw" / f"trajectory_{start.isoformat()}_{end.isoformat()}.json"


def fetch_trajectory_field(
    config: AtlasConfig,
    start: date,
    end: date,
    refresh: bool = False,
) -> TrajectoryField:
    """Fetch the coarse wide-domain wind field the back-trajectory integrates through."""
    settings = config.trajectory
    empty = TrajectoryField([], np.array([]), np.array([]), np.array([]), np.array([]), np.array([]), settings.level_hpa, [])
    if not settings.enabled:
        return TrajectoryField(
            [], np.array([]), np.array([]), np.array([]), np.array([]), np.array([]),
            settings.level_hpa, ["Back-trajectory ingestion is disabled."],
        )

    latitudes = np.arange(
        settings.latitude_min, settings.latitude_max + settings.grid_step_degrees / 2.0, settings.grid_step_degrees
    )
    longitudes = np.arange(
        settings.longitude_min, settings.longitude_max + settings.grid_step_degrees / 2.0, settings.grid_step_degrees
    )
    requested_latitudes = np.repeat(latitudes, len(longitudes))
    requested_longitudes = np.tile(longitudes, len(latitudes))
    level = settings.level_hpa
    variables = [
        f"wind_speed_{level}hPa",
        f"wind_direction_{level}hPa",
        f"temperature_{level}hPa",
    ]
    # The trajectory runs backwards from the period end, so the field must begin
    # early enough to cover it.
    field_start = start - pd.Timedelta(hours=settings.hours).to_pytimedelta()
    cache = _cache_path(config, field_start, end)
    try:
        if cache.exists() and not refresh:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        else:
            payload = fetch_json_with_retry(
                HISTORICAL_FORECAST_URL,
                {
                    "latitude": ",".join(f"{value:.3f}" for value in requested_latitudes),
                    "longitude": ",".join(f"{value:.3f}" for value in requested_longitudes),
                    "start_date": field_start.isoformat(),
                    "end_date": end.isoformat(),
                    "hourly": ",".join(variables),
                    "timezone": "UTC",
                    "wind_speed_unit": "ms",
                },
            )
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        locations = payload if isinstance(payload, list) else [payload]
        if len(locations) != len(requested_latitudes):
            raise ValueError(
                f"Expected {len(requested_latitudes)} trajectory grid points, received {len(locations)}."
            )
        times = pd.to_datetime(locations[0].get("hourly", {}).get("time", []), utc=True)
        if len(times) < 2:
            raise ValueError("The trajectory field returned too few timestamps.")

        shape = (len(times), len(latitudes), len(longitudes))
        speed = np.full(shape, np.nan, dtype=float)
        direction = np.full(shape, np.nan, dtype=float)
        temperature = np.full(shape, np.nan, dtype=float)
        for position, location in enumerate(locations):
            hourly = location.get("hourly", {})
            lat_index, lon_index = divmod(position, len(longitudes))
            speed[:, lat_index, lon_index] = pd.to_numeric(
                pd.Series(hourly.get(variables[0], [])), errors="coerce"
            ).to_numpy(dtype=float)
            direction[:, lat_index, lon_index] = pd.to_numeric(
                pd.Series(hourly.get(variables[1], [])), errors="coerce"
            ).to_numpy(dtype=float)
            temperature[:, lat_index, lon_index] = pd.to_numeric(
                pd.Series(hourly.get(variables[2], [])), errors="coerce"
            ).to_numpy(dtype=float)

        radians = np.radians(direction)
        wind_u = -speed * np.sin(radians)
        wind_v = -speed * np.cos(radians)
        return TrajectoryField(
            times=list(times),
            latitudes=latitudes,
            longitudes=longitudes,
            wind_u_ms=wind_u,
            wind_v_ms=wind_v,
            temperature_c=temperature,
            level_hpa=level,
            notes=[
                f"Back-trajectory wind field at {level} hPa on a "
                f"{settings.grid_step_degrees:g}-degree grid from Open-Meteo.",
            ],
        )
    except Exception as exc:
        if settings.required:
            raise RuntimeError(f"Required trajectory field was unavailable: {exc}") from exc
        return TrajectoryField(
            [], np.array([]), np.array([]), np.array([]), np.array([]), np.array([]),
            level, [f"Back-trajectory field was unavailable: {exc}"],
        )
