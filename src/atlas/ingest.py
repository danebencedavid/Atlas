from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from atlas.config import AtlasConfig
from atlas.dates import local_period_to_utc_bounds

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

HOURLY_VARIABLES = [
    "temperature_2m",
    "dew_point_2m",
    "relative_humidity_2m",
    "precipitation",
    "cloud_cover",
    "pressure_msl",
    "wind_speed_10m",
    "wind_speed_100m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "sunshine_duration",
]


def fetch_json_with_retry(url: str, params: dict[str, Any], retries: int = 4, backoff: float = 1.8) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=45)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(payload.get("reason", "Open-Meteo API returned an error."))
            return payload
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            last_error = exc
            if attempt == retries - 1:
                break
            time.sleep(backoff**attempt)
    raise RuntimeError(f"Failed to fetch weather data after {retries} attempts: {last_error}") from last_error


def _cache_path(config: AtlasConfig, start: date, end: date, data_dir: Path) -> Path:
    slug = f"{config.location.name.lower()}_{start.isoformat()}_{end.isoformat()}".replace(" ", "_")
    return data_dir / "raw" / f"open_meteo_localperiod_{slug}.json"


def fetch_open_meteo_period(
    config: AtlasConfig,
    start: date,
    end: date,
    data_dir: Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    data_dir = data_dir or config.outputs.data_dir
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(config, start, end, data_dir)

    if cache_file.exists() and not refresh:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        utc_start, utc_end_exclusive = local_period_to_utc_bounds(start, end, config.location.timezone)
        utc_end_inclusive = utc_end_exclusive - timedelta(hours=1)
        params = {
            "latitude": config.location.latitude,
            "longitude": config.location.longitude,
            "start_date": utc_start.date().isoformat(),
            "end_date": utc_end_inclusive.date().isoformat(),
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": "UTC",
            "wind_speed_unit": "ms",
        }
        payload = fetch_json_with_retry(OPEN_METEO_ARCHIVE_URL, params)
        cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    hourly = payload.get("hourly")
    if not hourly or "time" not in hourly:
        raise ValueError("Open-Meteo response did not include hourly time series.")

    frame = pd.DataFrame(hourly)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    utc_start, utc_end_exclusive = local_period_to_utc_bounds(start, end, config.location.timezone)
    frame = frame[(frame["time"] >= utc_start) & (frame["time"] < utc_end_exclusive)]
    frame = frame.sort_values("time").reset_index(drop=True)
    return frame


def fetch_open_meteo_week(
    config: AtlasConfig,
    start: date,
    end: date,
    data_dir: Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """Backward-compatible wrapper around period ingestion."""
    return fetch_open_meteo_period(config, start, end, data_dir=data_dir, refresh=refresh)
