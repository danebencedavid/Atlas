from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from atlas.anomalies import Anomaly, compute_anomalies, percentile_rank
from atlas.config import AtlasConfig
from atlas.ingest import OPEN_METEO_ARCHIVE_URL, fetch_json_with_retry


DAILY_VARIABLES = [
    "temperature_2m_mean",
    "precipitation_sum",
    "wind_speed_100m_mean",
    "wind_speed_10m_mean",
    "pressure_msl_mean",
    "cloud_cover_mean",
    "shortwave_radiation_sum",
    "et0_fao_evapotranspiration_sum",
]


@dataclass(frozen=True)
class ClimateReference:
    standard_table: pd.DataFrame
    recent_table: pd.DataFrame
    full_record_table: pd.DataFrame
    standard_anomalies: list[Anomaly]
    recent_anomalies: list[Anomaly]
    full_record_percentiles: dict[str, float]
    notes: list[str]


def _cache_path(config: AtlasConfig, year: int) -> Path:
    return (
        config.outputs.data_dir
        / "raw"
        / f"open_meteo_era5_daily_{year}.json"
    )


def _payload_frame(payload: dict) -> pd.DataFrame:
    daily = payload.get("daily", {})
    frame = pd.DataFrame(daily)
    if frame.empty or "time" not in frame:
        raise ValueError("ERA5 climatology response contained no daily data.")
    frame["date"] = pd.to_datetime(frame.pop("time"), errors="coerce").dt.date
    for variable in DAILY_VARIABLES:
        if variable in frame:
            frame[variable] = pd.to_numeric(frame[variable], errors="coerce")
    return frame


def fetch_climate_archive(
    config: AtlasConfig,
    report_start: date,
    refresh: bool = False,
) -> pd.DataFrame:
    final_year = report_start.year - 1
    years = list(range(config.climatology.archive_start_year, final_year + 1))
    payloads: dict[int, dict] = {}
    missing_years: list[int] = []

    for year in years:
        cache = _cache_path(config, year)
        # Completed ERA5 years are immutable reference data. A weather refresh
        # must not turn into a multi-decade climatology refresh.
        if cache.exists():
            payloads[year] = json.loads(cache.read_text(encoding="utf-8"))
        else:
            missing_years.append(year)

    def fetch_year(year: int) -> tuple[int, dict]:
        payload = fetch_json_with_retry(
            OPEN_METEO_ARCHIVE_URL,
            {
                "latitude": config.location.latitude,
                "longitude": config.location.longitude,
                "start_date": date(year, 1, 1).isoformat(),
                "end_date": date(year, 12, 31).isoformat(),
                "daily": ",".join(DAILY_VARIABLES),
                "timezone": config.location.timezone,
                "wind_speed_unit": "ms",
                "models": "era5",
            },
        )
        cache = _cache_path(config, year)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return year, payload

    # Annual requests keep each provider call modest. Caching each completed
    # year also makes an interrupted first run resumable.
    for offset in range(0, len(missing_years), 3):
        batch = missing_years[offset : offset + 3]
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            for year, payload in executor.map(fetch_year, batch):
                payloads[year] = payload

    frames = [_payload_frame(payloads[year]) for year in years]
    frame = pd.concat(frames, ignore_index=True)
    required = {
        "temperature_2m_mean",
        "precipitation_sum",
        "pressure_msl_mean",
        "cloud_cover_mean",
        "shortwave_radiation_sum",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"ERA5 climatology response omitted required variables: {', '.join(missing)}")
    return frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def _safe_year(value: date, year: int) -> date:
    try:
        return value.replace(year=year)
    except ValueError:
        return value.replace(year=year, day=28)


def _aggregate_daily(group: pd.DataFrame) -> dict[str, float]:
    wind_column = (
        "wind_speed_100m_mean"
        if "wind_speed_100m_mean" in group
        and pd.to_numeric(group["wind_speed_100m_mean"], errors="coerce").notna().any()
        else "wind_speed_10m_mean"
    )
    et0 = (
        pd.to_numeric(group["et0_fao_evapotranspiration_sum"], errors="coerce").sum()
        if "et0_fao_evapotranspiration_sum" in group
        else float("nan")
    )
    precipitation = pd.to_numeric(group["precipitation_sum"], errors="coerce").sum()
    return {
        "temperature_mean_c": float(pd.to_numeric(group["temperature_2m_mean"], errors="coerce").mean()),
        "precipitation_total_mm": float(precipitation),
        "wind_speed_mean_ms": float(pd.to_numeric(group[wind_column], errors="coerce").mean()),
        "pressure_mean_hpa": float(pd.to_numeric(group["pressure_msl_mean"], errors="coerce").mean()),
        "cloud_cover_mean_pct": float(pd.to_numeric(group["cloud_cover_mean"], errors="coerce").mean()),
        "shortwave_total_wh_m2": float(
            pd.to_numeric(group["shortwave_radiation_sum"], errors="coerce").sum()
            * 277.7777778
        ),
        "et0_total_mm": float(et0),
        "water_balance_mm": float(precipitation - et0),
    }


def period_table(
    archive: pd.DataFrame,
    report_start: date,
    report_end: date,
    first_year: int,
    final_year: int,
) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    duration = report_end - report_start
    indexed = archive.set_index("date")
    for year in range(first_year, final_year + 1):
        window_start = _safe_year(report_start, year)
        window_end = window_start + duration
        dates = [window_start + timedelta(days=offset) for offset in range(duration.days + 1)]
        available = [value for value in dates if value in indexed.index]
        if len(available) != len(dates):
            continue
        group = indexed.loc[available].reset_index()
        row: dict[str, float | int] = _aggregate_daily(group)
        row["baseline_year"] = year
        rows.append(row)
    return pd.DataFrame(rows)


def build_climate_reference(
    config: AtlasConfig,
    archive: pd.DataFrame,
    current_metrics: dict[str, float],
    report_start: date,
    report_end: date,
    recent_table: pd.DataFrame | None = None,
) -> ClimateReference:
    standard = period_table(
        archive,
        report_start,
        report_end,
        config.climatology.standard_start_year,
        config.climatology.standard_end_year,
    )
    if len(standard) < config.climatology.minimum_standard_years:
        raise RuntimeError(
            f"Only {len(standard)} standard-normal years were available; "
            f"{config.climatology.minimum_standard_years} are required."
        )
    full_record = period_table(
        archive,
        report_start,
        report_end,
        config.climatology.archive_start_year,
        report_start.year - 1,
    )
    if recent_table is None:
        recent_table = period_table(
            archive,
            report_start,
            report_end,
            report_start.year - config.baseline.years,
            report_start.year - 1,
        )
    if len(recent_table) < config.baseline.minimum_years:
        raise RuntimeError(
            f"Only {len(recent_table)} recent-climate years were available; "
            f"{config.baseline.minimum_years} are required."
        )
    standard_anomalies = compute_anomalies(current_metrics, standard)
    recent_anomalies = compute_anomalies(current_metrics, recent_table)
    full_percentiles = {
        item.metric: percentile_rank(
            float(current_metrics[item.metric]),
            pd.to_numeric(full_record[item.metric], errors="coerce"),
        )
        for item in standard_anomalies
    }
    notes = [
        (
            f"Standard anomalies use {len(standard)} same-calendar ERA5 periods from "
            f"{config.climatology.standard_start_year}-{config.climatology.standard_end_year}."
        ),
        (
            f"Full-record percentiles use {len(full_record)} same-calendar periods from "
            f"{config.climatology.archive_start_year}-{report_start.year - 1}."
        ),
        (
            f"The recent-climate comparison uses {len(recent_table)} periods and remains "
            "separate from the WMO standard-normal window."
        ),
    ]
    return ClimateReference(
        standard,
        recent_table,
        full_record,
        standard_anomalies,
        recent_anomalies,
        full_percentiles,
        notes,
    )


def standard_water_balance_samples(
    config: AtlasConfig,
    archive: pd.DataFrame,
    report_end: date,
    days: int,
) -> pd.Series:
    start = report_end - timedelta(days=days - 1)
    table = period_table(
        archive,
        start,
        report_end,
        config.climatology.standard_start_year,
        config.climatology.standard_end_year,
    )
    if "water_balance_mm" not in table:
        return pd.Series(dtype="float64")
    return pd.to_numeric(table["water_balance_mm"], errors="coerce").dropna()
