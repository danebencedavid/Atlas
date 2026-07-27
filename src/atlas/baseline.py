from __future__ import annotations

from datetime import date

import pandas as pd

from atlas.config import AtlasConfig
from atlas.ingest import fetch_open_meteo_week
from atlas.quality import validate_hourly_week


def same_calendar_window(start: date, end: date, year: int) -> tuple[date, date]:
    """Map a week to the same month/day window in another year."""
    try:
        mapped_start = start.replace(year=year)
    except ValueError:
        mapped_start = start.replace(year=year, day=28)
    try:
        mapped_end = end.replace(year=year)
    except ValueError:
        mapped_end = end.replace(year=year, day=28)
    return mapped_start, mapped_end


def baseline_windows(start: date, end: date, years: int) -> list[tuple[date, date]]:
    return [same_calendar_window(start, end, year) for year in range(start.year - years, start.year)]


def fetch_baseline(config: AtlasConfig, start: date, end: date, refresh: bool = False) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    for window_start, window_end in baseline_windows(start, end, config.baseline.years):
        try:
            frame = fetch_open_meteo_week(config, window_start, window_end, refresh=refresh).copy()
            quality = validate_hourly_week(
                frame,
                window_start,
                window_end,
                config.location.timezone,
                minimum_coverage=config.operations.minimum_hourly_coverage,
            )
            if not quality.ok:
                failures.append(f"{window_start.year}: {' '.join(quality.notes)}")
                continue
        except Exception as exc:
            failures.append(f"{window_start.year}: {exc}")
            continue
        frame["baseline_year"] = window_start.year
        frames.append(frame)

    if len(frames) < config.baseline.minimum_years:
        raise RuntimeError(
            f"Only fetched {len(frames)} valid baseline years, below minimum {config.baseline.minimum_years}. "
            f"Failures: {' | '.join(failures)}"
        )
    return pd.concat(frames, ignore_index=True)
