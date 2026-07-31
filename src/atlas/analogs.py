from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.config import AtlasConfig
from atlas.ingest import OPEN_METEO_ARCHIVE_URL, fetch_json_with_retry


DAILY_VARIABLES = [
    "temperature_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_mean",
    "shortwave_radiation_sum",
    "cloud_cover_mean",
    "pressure_msl_mean",
]

FEATURES = [
    "temperature_mean_c",
    "precipitation_total_mm",
    "wind_speed_10m_mean_ms",
    "shortwave_total_mj_m2",
    "cloud_cover_mean_pct",
    "pressure_mean_hpa",
]

WEIGHTS = np.array([1.2, 1.0, 1.0, 1.0, 0.8, 0.8], dtype=float)


@dataclass(frozen=True)
class AnalogPeriod:
    start_date: str
    end_date: str
    similarity: float
    distance: float
    character: str
    metrics: dict[str, float]


@dataclass(frozen=True)
class AnalogAnalysis:
    matches: list[AnalogPeriod]
    archive: pd.DataFrame
    notes: list[str]


def _cache_path(config: AtlasConfig, report_year: int) -> Path:
    first_year = report_year - config.analogs.years
    return (
        config.outputs.data_dir
        / "raw"
        / f"open_meteo_analog_daily_{first_year}_{report_year - 1}.json"
    )


def fetch_analog_daily_archive(
    config: AtlasConfig,
    report_start: date,
    refresh: bool = False,
) -> pd.DataFrame:
    cache = _cache_path(config, report_start.year)
    if cache.exists() and not refresh:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        payload = fetch_json_with_retry(
            OPEN_METEO_ARCHIVE_URL,
            {
                "latitude": config.location.latitude,
                "longitude": config.location.longitude,
                "start_date": date(report_start.year - config.analogs.years, 1, 1).isoformat(),
                "end_date": date(report_start.year - 1, 12, 31).isoformat(),
                "daily": ",".join(DAILY_VARIABLES),
                "timezone": config.location.timezone,
                "wind_speed_unit": "ms",
                "models": "era5",
            },
        )
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    daily = payload.get("daily", {})
    frame = pd.DataFrame(daily)
    if frame.empty or "time" not in frame:
        raise ValueError("Analog archive response contained no daily data.")
    frame["date"] = pd.to_datetime(frame.pop("time")).dt.date
    for column in DAILY_VARIABLES:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _period_archive(frame: pd.DataFrame, window_days: int) -> pd.DataFrame:
    ordered = frame.sort_values("date").reset_index(drop=True)
    periods = pd.DataFrame(
        {
            "start_date": ordered["date"],
            "end_date": ordered["date"].shift(-(window_days - 1)),
            "temperature_mean_c": ordered["temperature_2m_mean"].rolling(window_days).mean().shift(-(window_days - 1)),
            "precipitation_total_mm": ordered["precipitation_sum"].rolling(window_days).sum().shift(-(window_days - 1)),
            "wind_speed_10m_mean_ms": ordered["wind_speed_10m_mean"].rolling(window_days).mean().shift(-(window_days - 1)),
            "shortwave_total_mj_m2": ordered["shortwave_radiation_sum"].rolling(window_days).sum().shift(-(window_days - 1)),
            "cloud_cover_mean_pct": ordered["cloud_cover_mean"].rolling(window_days).mean().shift(-(window_days - 1)),
            "pressure_mean_hpa": ordered["pressure_msl_mean"].rolling(window_days).mean().shift(-(window_days - 1)),
        }
    ).dropna()
    periods["mid_date"] = periods["start_date"].map(
        lambda value: value + timedelta(days=(window_days - 1) // 2)
    )
    return periods.reset_index(drop=True)


def _cyclic_day_distance(first: int, second: int) -> int:
    difference = abs(first - second)
    return min(difference, 366 - difference)


def _current_vector(current: pd.DataFrame) -> dict[str, float]:
    return {
        "temperature_mean_c": float(pd.to_numeric(current["temperature_2m"], errors="coerce").mean()),
        "precipitation_total_mm": float(pd.to_numeric(current["precipitation"], errors="coerce").sum()),
        "wind_speed_10m_mean_ms": float(pd.to_numeric(current["wind_speed_10m"], errors="coerce").mean()),
        "shortwave_total_mj_m2": float(pd.to_numeric(current["shortwave_radiation"], errors="coerce").sum() / 277.7777778),
        "cloud_cover_mean_pct": float(pd.to_numeric(current["cloud_cover"], errors="coerce").mean()),
        "pressure_mean_hpa": float(pd.to_numeric(current["pressure_msl"], errors="coerce").mean()),
    }


def _character(metrics: dict[str, float], climatology: pd.Series) -> str:
    signals = []
    if metrics["temperature_mean_c"] >= climatology["temperature_mean_c"] + 2:
        signals.append("warm")
    elif metrics["temperature_mean_c"] <= climatology["temperature_mean_c"] - 2:
        signals.append("cool")
    if metrics["precipitation_total_mm"] >= max(5.0, climatology["precipitation_total_mm"] * 1.5):
        signals.append("wet")
    elif metrics["precipitation_total_mm"] <= 0.5:
        signals.append("dry")
    if metrics["wind_speed_10m_mean_ms"] >= climatology["wind_speed_10m_mean_ms"] + 1.0:
        signals.append("windy")
    if metrics["shortwave_total_mj_m2"] >= climatology["shortwave_total_mj_m2"] * 1.15:
        signals.append("bright")
    elif metrics["cloud_cover_mean_pct"] >= climatology["cloud_cover_mean_pct"] + 15:
        signals.append("cloudy")
    return ", ".join(signals[:3]) if signals else "seasonally typical mixed weather"


def find_historical_analogs(
    config: AtlasConfig,
    current: pd.DataFrame,
    report_start: date,
    refresh: bool = False,
) -> AnalogAnalysis:
    if not config.analogs.enabled:
        return AnalogAnalysis([], pd.DataFrame(), ["Historical analog analysis is disabled."])
    try:
        daily = fetch_analog_daily_archive(config, report_start, refresh=refresh)
        archive = _period_archive(daily, config.reporting.window_days)
        target_doy = (report_start + timedelta(days=1)).timetuple().tm_yday
        archive = archive[
            archive["mid_date"].map(
                lambda value: _cyclic_day_distance(value.timetuple().tm_yday, target_doy)
                <= config.analogs.season_window_days
            )
        ].copy()
        archive = archive.dropna(subset=FEATURES)
        if len(archive) < config.analogs.count:
            raise ValueError("Too few seasonally comparable periods were available.")

        current_metrics = _current_vector(current)
        center = archive[FEATURES].median()
        spread = archive[FEATURES].std(ddof=1).replace(0.0, np.nan).fillna(1.0)
        z_archive = (archive[FEATURES] - center) / spread
        z_current = (pd.Series(current_metrics)[FEATURES] - center) / spread
        archive["distance"] = np.sqrt(
            ((z_archive - z_current) ** 2 * WEIGHTS).sum(axis=1) / WEIGHTS.sum()
        )
        archive = archive.sort_values("distance")
        selected_rows = []
        for _, row in archive.iterrows():
            if any(abs((row["start_date"] - selected["start_date"]).days) < 7 for selected in selected_rows):
                continue
            selected_rows.append(row)
            if len(selected_rows) >= config.analogs.count:
                break
        climatology = archive[FEATURES].median()
        matches = []
        for row in selected_rows:
            metrics = {feature: float(row[feature]) for feature in FEATURES}
            distance = float(row["distance"])
            matches.append(
                AnalogPeriod(
                    start_date=row["start_date"].isoformat(),
                    end_date=row["end_date"].isoformat(),
                    similarity=round(100.0 * math.exp(-0.5 * distance**2), 1),
                    distance=round(distance, 3),
                    character=_character(metrics, climatology),
                    metrics=metrics,
                )
            )
        notes = [
            f"Analogs are selected from {config.analogs.years} years of ERA5 daily data within +/-{config.analogs.season_window_days} calendar days.",
            "Similarity uses standardized temperature, precipitation, wind, radiation, cloud and pressure; it is descriptive rather than predictive.",
        ]
        return AnalogAnalysis(matches, archive, notes)
    except Exception as exc:
        return AnalogAnalysis([], pd.DataFrame(), [f"Historical analog analysis unavailable: {exc}"])
