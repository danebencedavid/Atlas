from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from atlas.config import AtlasConfig
from atlas.dates import local_period_to_utc_bounds
from atlas.hungaromet import _cached_bytes, _request_bytes


SATELLITE_ROOT = "https://odp.met.hu/weather/satellite/MSG/png"


@dataclass(frozen=True)
class SatelliteFrame:
    time: pd.Timestamp
    product: str
    path: Path


@dataclass(frozen=True)
class SatelliteArchive:
    frames: dict[str, list[SatelliteFrame]]
    notes: list[str]

    @property
    def frame_count(self) -> int:
        return sum(len(items) for items in self.frames.values())


def _listed_frames(product: str) -> list[tuple[pd.Timestamp, str]]:
    url = f"{SATELLITE_ROOT}/{product}/"
    index = _request_bytes(url).decode("utf-8", errors="replace")
    pattern = re.compile(
        rf'href="(satellite_MSG-{re.escape(product)}-(\d{{8}}_\d{{4}})\.png)"'
    )
    selected: dict[str, tuple[pd.Timestamp, str]] = {}
    for filename, stamp in pattern.findall(index):
        timestamp = pd.to_datetime(stamp, format="%Y%m%d_%H%M", utc=True)
        selected[filename] = (timestamp, filename)
    return sorted(selected.values(), key=lambda item: item[0])


def _sample(
    items: list[tuple[pd.Timestamp, str]],
    interval_minutes: int,
) -> list[tuple[pd.Timestamp, str]]:
    sampled: list[tuple[pd.Timestamp, str]] = []
    last: pd.Timestamp | None = None
    interval = pd.Timedelta(minutes=max(interval_minutes, 15))
    for item in items:
        if last is None or item[0] - last >= interval:
            sampled.append(item)
            last = item[0]
    return sampled


def _download_frame(
    config: AtlasConfig,
    product: str,
    item: tuple[pd.Timestamp, str],
    refresh: bool,
) -> SatelliteFrame:
    timestamp, filename = item
    url = f"{SATELLITE_ROOT}/{product}/{filename}"
    cache = config.outputs.data_dir / "raw" / "hungaromet" / "satellite" / product / filename
    _cached_bytes(url, cache, refresh)
    return SatelliteFrame(timestamp, product, cache)


def fetch_satellite_archive(
    config: AtlasConfig,
    start: date,
    end: date,
    refresh: bool = False,
) -> SatelliteArchive:
    if not config.satellite.enabled:
        return SatelliteArchive({}, ["Meteosat ingestion is disabled."])
    utc_start, utc_end = local_period_to_utc_bounds(start, end, config.location.timezone)
    frames: dict[str, list[SatelliteFrame]] = {}
    failures: list[str] = []
    requests: list[tuple[str, tuple[pd.Timestamp, str]]] = []
    for product in config.satellite.products:
        try:
            available = [
                item for item in _listed_frames(product) if utc_start <= item[0] < utc_end
            ]
            for item in _sample(available, config.satellite.frame_interval_minutes):
                requests.append((product, item))
        except Exception as exc:
            failures.append(f"{product}: {exc}")

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_download_frame, config, product, item, refresh): (product, item)
            for product, item in requests
        }
        for future in as_completed(futures):
            product, item = futures[future]
            try:
                frame = future.result()
                frames.setdefault(product, []).append(frame)
            except Exception as exc:
                failures.append(f"{product} {item[0].isoformat()}: {exc}")
    for product_frames in frames.values():
        product_frames.sort(key=lambda item: item.time)

    if not frames:
        message = "No Meteosat frames were available in the provider's rolling archive."
        if failures:
            message += f" First failure: {failures[0]}"
        if config.satellite.required:
            raise RuntimeError(message)
        return SatelliteArchive({}, [message])

    notes = [
        (
            "HungaroMet Meteosat Second Generation RGB and infrared products; "
            f"frames sampled approximately every {config.satellite.frame_interval_minutes} minutes."
        ),
        "Satellite imagery is synchronized by nearest timestamp with radar and LINET timelines, not spatially overlaid.",
    ]
    if failures:
        notes.append(f"{len(failures)} satellite listings or frame downloads failed and were skipped.")
    return SatelliteArchive(frames, notes)
