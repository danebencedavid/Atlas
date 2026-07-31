from __future__ import annotations

import io
import math
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy.io import netcdf_file

from atlas.config import AtlasConfig
from atlas.dates import local_period_to_utc_bounds


STATION_URL = (
    "https://odp.met.hu/climate/observations_hungary/10_minutes/recent/"
    "HABP_10M_{station_id}_akt.zip"
)
RADAR_INDEX_URL = "https://odp.met.hu/weather/radar/composite/nc/refl2D/"
LIGHTNING_URL = "https://odp.met.hu/weather/lightning/alHa/alHa{day}_0000.txt.zip"


@dataclass(frozen=True)
class StationObservations:
    frame: pd.DataFrame
    station_id: int
    station_name: str
    notes: list[str]


@dataclass(frozen=True)
class RadarArchive:
    times: list[pd.Timestamp]
    latitudes: np.ndarray
    longitudes: np.ndarray
    reflectivity_dbz: np.ndarray
    accumulation_mm: np.ndarray
    timeline: pd.DataFrame
    notes: list[str]


@dataclass(frozen=True)
class LightningArchive:
    frame: pd.DataFrame
    hourly: pd.DataFrame
    notes: list[str]


def _request_bytes(url: str, retries: int = 4, backoff: float = 1.7) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=45)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(backoff**attempt)
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts: {last_error}")


def _cached_bytes(url: str, path: Path, refresh: bool) -> bytes:
    if path.exists() and not refresh:
        return path.read_bytes()
    payload = _request_bytes(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _zip_text(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if not names:
            raise ValueError("Downloaded ZIP archive contained no data file.")
        return archive.read(names[0]).decode("utf-8-sig", errors="replace")


def _parse_station_csv(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    header_index = next(
        index
        for index, line in enumerate(lines)
        if not line.lstrip().startswith("#")
        and (line.lstrip().startswith("StationNumber;") or "Time;" in line)
    )
    frame = pd.read_csv(io.StringIO("\n".join(lines[header_index:])), sep=";", dtype=str)
    frame.columns = [column.strip() for column in frame.columns]
    frame = frame.rename(columns={column: column.strip() for column in frame.columns})
    for column in frame.columns:
        frame[column] = frame[column].str.strip()

    timestamp = pd.to_datetime(frame["Time"], format="%Y%m%d%H%M", errors="coerce", utc=True)
    output = pd.DataFrame({"time": timestamp})
    if "StationNumber" in frame:
        output["station_id"] = pd.to_numeric(frame["StationNumber"], errors="coerce")
    else:
        metadata = re.search(r"(?im)^#\s*StationNumber\s*:\s*(\d+)", text)
        if metadata:
            output["station_id"] = int(metadata.group(1))
    variables = {
        "r": "precipitation_mm",
        "t": "temperature_c",
        "v": "visibility_m",
        "p": "pressure_msl_hpa",
        "u": "relative_humidity_pct",
        "fs": "wind_speed_ms",
        "fsd": "wind_direction_deg",
        "fx": "wind_gust_ms",
    }
    for source, target in variables.items():
        values = pd.to_numeric(
            frame[source] if source in frame else pd.Series(np.nan, index=frame.index),
            errors="coerce",
        )
        output[target] = values.mask(values <= -999)
    output = output.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    return output


def fetch_station_observations(
    config: AtlasConfig,
    start: date,
    end: date,
    refresh: bool = False,
) -> StationObservations:
    station = config.hungaromet
    if not station.enabled:
        return StationObservations(
            pd.DataFrame(), station.station_id, station.station_name, ["HungaroMet ingestion is disabled."]
        )
    cache = (
        config.outputs.data_dir
        / "raw"
        / "hungaromet"
        / f"station_{station.station_id}_{start.year}.zip"
    )
    url = STATION_URL.format(station_id=station.station_id)
    try:
        frame = _parse_station_csv(_zip_text(_cached_bytes(url, cache, refresh)))
        utc_start, utc_end = local_period_to_utc_bounds(start, end, config.location.timezone)
        frame = frame[(frame["time"] >= utc_start) & (frame["time"] < utc_end)].copy()
        if frame.empty:
            raise ValueError("The station archive contained no rows for the reporting period.")
        expected = int((utc_end - utc_start).total_seconds() / 600)
        coverage = len(frame) / expected if expected else 0.0
        notes = [
            f"HungaroMet station {station.station_id} ({station.station_name}); 10-minute observations.",
            f"Station coverage: {len(frame)}/{expected} expected records ({coverage:.0%}).",
        ]
        return StationObservations(frame, station.station_id, station.station_name, notes)
    except Exception as exc:
        if station.required:
            raise RuntimeError(f"Required HungaroMet station data was unavailable: {exc}") from exc
        return StationObservations(
            pd.DataFrame(), station.station_id, station.station_name, [f"Station observations unavailable: {exc}"]
        )


def station_hourly(observations: StationObservations) -> pd.DataFrame:
    if observations.frame.empty:
        return pd.DataFrame()
    frame = observations.frame.set_index("time")
    means = frame.resample("1h").mean(numeric_only=True)
    if {"temperature_c", "relative_humidity_pct"}.issubset(frame.columns):
        temperature = pd.to_numeric(frame["temperature_c"], errors="coerce")
        humidity = pd.to_numeric(frame["relative_humidity_pct"], errors="coerce").clip(1.0, 100.0)
        alpha = np.log(humidity / 100.0) + 17.625 * temperature / (243.04 + temperature)
        dew_point = 243.04 * alpha / (17.625 - alpha)
        means["dew_point_c"] = dew_point.resample("1h").mean()
    if {"wind_speed_ms", "wind_direction_deg"}.issubset(frame.columns):
        direction = np.radians(pd.to_numeric(frame["wind_direction_deg"], errors="coerce"))
        speed = pd.to_numeric(frame["wind_speed_ms"], errors="coerce")
        eastward = (-speed * np.sin(direction)).resample("1h").mean()
        northward = (-speed * np.cos(direction)).resample("1h").mean()
        means["wind_direction_deg"] = (
            np.degrees(np.arctan2(-eastward, -northward)) + 360.0
        ) % 360.0
    if "precipitation_mm" in frame:
        means["precipitation_mm"] = frame["precipitation_mm"].resample("1h").sum(min_count=1)
    if "wind_gust_ms" in frame:
        means["wind_gust_ms"] = frame["wind_gust_ms"].resample("1h").max()
    return means.reset_index()


def _radar_names(start: date, end: date, interval_minutes: int) -> list[tuple[pd.Timestamp, str]]:
    index = _request_bytes(RADAR_INDEX_URL).decode("utf-8", errors="replace")
    names = re.findall(r'href="(radar_composite-refl2D-(\d{8}_\d{4})\.nc\.zip)"', index)
    selected: dict[str, tuple[pd.Timestamp, str]] = {}
    for name, stamp in names:
        timestamp = pd.to_datetime(stamp, format="%Y%m%d_%H%M", utc=True)
        if timestamp.minute % interval_minutes == 0:
            selected[name] = (timestamp, name)
    return sorted(selected.values(), key=lambda item: item[0])


def _decode_radar(payload: bytes, config: AtlasConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = next(name for name in archive.namelist() if name.endswith(".nc"))
        raw_netcdf = archive.read(name)
    with netcdf_file(io.BytesIO(raw_netcdf), mmap=False) as dataset:
        raw = np.asarray(dataset.variables["refl2D"].data).copy().view(np.uint8)
        lat0 = float(np.asarray(dataset.variables["La1"].data))
        lon0 = float(np.asarray(dataset.variables["Lo1"].data))
        dy = float(np.asarray(dataset.variables["Dy"].data))
        dx = float(np.asarray(dataset.variables["Dx"].data))
    latitudes = lat0 - np.arange(raw.shape[0]) * dy
    longitudes = lon0 + np.arange(raw.shape[1]) * dx
    radius = config.hungaromet.radar_radius_km
    lat_delta = radius / 111.0
    lon_delta = radius / (111.0 * math.cos(math.radians(config.location.latitude)))
    lat_mask = np.abs(latitudes - config.location.latitude) <= lat_delta
    lon_mask = np.abs(longitudes - config.location.longitude) <= lon_delta
    dbz = raw.astype(float) / 2.0 - 32.0
    dbz[(dbz < 0.0) | (dbz > 75.0)] = np.nan
    return latitudes[lat_mask], longitudes[lon_mask], dbz[np.ix_(lat_mask, lon_mask)]


def _download_radar_frame(
    config: AtlasConfig,
    item: tuple[pd.Timestamp, str],
    refresh: bool,
) -> tuple[pd.Timestamp, np.ndarray, np.ndarray, np.ndarray]:
    timestamp, name = item
    cache = config.outputs.data_dir / "raw" / "hungaromet" / "radar" / name
    payload = _cached_bytes(RADAR_INDEX_URL + name, cache, refresh)
    latitudes, longitudes, dbz = _decode_radar(payload, config)
    return timestamp, latitudes, longitudes, dbz


def fetch_radar_archive(
    config: AtlasConfig,
    start: date,
    end: date,
    refresh: bool = False,
) -> RadarArchive:
    empty = RadarArchive([], np.array([]), np.array([]), np.empty((0, 0, 0)), np.empty((0, 0)), pd.DataFrame(), [])
    if not config.hungaromet.enabled:
        return RadarArchive(**{**empty.__dict__, "notes": ["HungaroMet radar ingestion is disabled."]})
    try:
        interval = config.hungaromet.radar_accumulation_interval_minutes
        utc_start, utc_end = local_period_to_utc_bounds(start, end, config.location.timezone)
        items = [
            item for item in _radar_names(start, end, interval)
            if utc_start <= item[0] < utc_end
        ]
        if not items:
            raise ValueError("No radar frames were listed for the reporting period.")
        decoded: list[tuple[pd.Timestamp, np.ndarray, np.ndarray, np.ndarray]] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(_download_radar_frame, config, item, refresh): item
                for item in items
            }
            for future in as_completed(futures):
                try:
                    decoded.append(future.result())
                except Exception as exc:
                    errors.append(f"{futures[future][0].isoformat()}: {exc}")
        decoded.sort(key=lambda item: item[0])
        if not decoded:
            raise ValueError(f"All radar frame downloads failed: {' | '.join(errors[:3])}")

        latitudes, longitudes = decoded[0][1], decoded[0][2]
        accumulation = np.zeros_like(decoded[0][3], dtype=float)
        timeline_rows = []
        replay_times: list[pd.Timestamp] = []
        replay_frames: list[np.ndarray] = []
        replay_interval = config.hungaromet.radar_replay_interval_minutes
        nearest_lat = int(np.argmin(np.abs(latitudes - config.location.latitude)))
        nearest_lon = int(np.argmin(np.abs(longitudes - config.location.longitude)))
        for timestamp, _, _, dbz in decoded:
            z = np.power(10.0, dbz / 10.0)
            rain_rate = np.power(z / 200.0, 1.0 / 1.6)
            rain_rate = np.nan_to_num(rain_rate, nan=0.0, posinf=0.0, neginf=0.0)
            accumulation += rain_rate * interval / 60.0
            timeline_rows.append(
                {
                    "time": timestamp,
                    "reflectivity_dbz": float(dbz[nearest_lat, nearest_lon])
                    if np.isfinite(dbz[nearest_lat, nearest_lon])
                    else float("nan"),
                    "domain_max_dbz": float(np.nanmax(dbz)) if np.isfinite(dbz).any() else float("nan"),
                    "echo_fraction_pct": float(np.isfinite(dbz).mean() * 100.0),
                }
            )
            if timestamp.minute % replay_interval == 0:
                replay_times.append(timestamp)
                replay_frames.append(dbz)
        expected = len(pd.date_range(utc_start, utc_end, freq=f"{interval}min", inclusive="left"))
        coverage = len(decoded) / expected if expected else 0.0
        stride = max(int(config.hungaromet.radar_display_stride), 1)
        notes = [
            f"HungaroMet 1 km composite radar sampled every {interval} minutes; {len(decoded)}/{expected} frames available ({coverage:.0%}).",
            f"The browser replay uses every {replay_interval} minutes and a {stride} km display grid for practical loading.",
            "Accumulation is a reflectivity-derived Z-R estimate and should be treated as a spatial precipitation proxy.",
        ]
        if errors:
            notes.append(f"{len(errors)} radar frames were unavailable and skipped.")
        return RadarArchive(
            replay_times,
            latitudes[::stride],
            longitudes[::stride],
            np.stack(replay_frames)[:, ::stride, ::stride]
            if replay_frames else np.empty((0, len(latitudes[::stride]), len(longitudes[::stride]))),
            accumulation[::stride, ::stride],
            pd.DataFrame(timeline_rows),
            notes,
        )
    except Exception as exc:
        if config.hungaromet.required:
            raise RuntimeError(f"Required HungaroMet radar data was unavailable: {exc}") from exc
        return RadarArchive(**{**empty.__dict__, "notes": [f"Radar archive unavailable: {exc}"]})


def _haversine_km(lat: np.ndarray, lon: np.ndarray, target_lat: float, target_lon: float) -> np.ndarray:
    earth_radius_km = 6371.0
    lat1 = np.radians(lat)
    lat2 = math.radians(target_lat)
    dlat = lat1 - lat2
    dlon = np.radians(lon - target_lon)
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * math.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return earth_radius_km * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))


def _parse_lightning(text: str) -> pd.DataFrame:
    rows = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 8:
            continue
        rows.append(
            {
                "time": pd.to_datetime(f"{fields[0]} {fields[1]}", utc=True, errors="coerce"),
                "latitude": float(fields[2]),
                "longitude": float(fields[3]),
                "height_km": float(fields[4]),
                "event_type": int(fields[5]),
                "peak_current_ka": float(fields[6]),
                "location_error": float(fields[7]),
            }
        )
    return pd.DataFrame(rows)


def fetch_lightning_archive(
    config: AtlasConfig,
    start: date,
    end: date,
    refresh: bool = False,
) -> LightningArchive:
    if not config.hungaromet.enabled:
        return LightningArchive(pd.DataFrame(), pd.DataFrame(), ["HungaroMet lightning ingestion is disabled."])
    frames = []
    failures = []
    day = start
    while day <= end:
        filename = f"alHa{day.strftime('%Y%m%d')}_0000.txt.zip"
        url = LIGHTNING_URL.format(day=day.strftime("%Y%m%d"))
        cache = config.outputs.data_dir / "raw" / "hungaromet" / "lightning" / filename
        try:
            frames.append(_parse_lightning(_zip_text(_cached_bytes(url, cache, refresh))))
        except Exception as exc:
            failures.append(f"{day.isoformat()}: {exc}")
        day += timedelta(days=1)
    if not frames:
        return LightningArchive(pd.DataFrame(), pd.DataFrame(), [f"Lightning data unavailable: {' | '.join(failures)}"])
    frame = pd.concat(frames, ignore_index=True).dropna(subset=["time"])
    utc_start, utc_end = local_period_to_utc_bounds(start, end, config.location.timezone)
    frame = frame[(frame["time"] >= utc_start) & (frame["time"] < utc_end)].copy()
    distance = _haversine_km(
        frame["latitude"].to_numpy(),
        frame["longitude"].to_numpy(),
        config.location.latitude,
        config.location.longitude,
    )
    frame["distance_km"] = distance
    frame = frame[distance <= config.hungaromet.lightning_radius_km].sort_values("time").reset_index(drop=True)
    if frame.empty:
        hourly = pd.DataFrame(columns=["time", "flash_count"])
    else:
        hourly = (
            frame.set_index("time")
            .resample("1h")
            .size()
            .rename("flash_count")
            .reset_index()
        )
    notes = [
        f"HungaroMet LINET events within {config.hungaromet.lightning_radius_km:.0f} km of Debrecen.",
        f"Detected {len(frame):,} lightning events in the reporting period.",
    ]
    if failures:
        notes.append(f"{len(failures)} daily lightning files were unavailable.")
    return LightningArchive(frame, hourly, notes)
