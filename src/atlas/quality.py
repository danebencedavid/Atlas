from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from atlas.dates import local_period_to_utc_bounds


REQUIRED_HOURLY_COLUMNS = [
    "temperature_2m",
    "dew_point_2m",
    "precipitation",
    "cloud_cover",
    "pressure_msl",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "shortwave_radiation",
]


@dataclass(frozen=True)
class DataQualityReport:
    ok: bool
    expected_hours: int
    observed_hours: int
    coverage: float
    missing_columns: list[str]
    sparse_columns: list[str]
    notes: list[str]


def expected_hour_count(start: date, end: date, timezone_name: str) -> int:
    utc_start, utc_end_exclusive = local_period_to_utc_bounds(start, end, timezone_name)
    return len(pd.date_range(utc_start, utc_end_exclusive, freq="h", inclusive="left"))


def validate_hourly_period(
    frame: pd.DataFrame,
    start: date,
    end: date,
    timezone_name: str,
    minimum_coverage: float = 0.95,
) -> DataQualityReport:
    expected = expected_hour_count(start, end, timezone_name)
    observed = int(frame["time"].nunique()) if "time" in frame else 0
    coverage = observed / expected if expected else 0.0
    missing_columns = [column for column in REQUIRED_HOURLY_COLUMNS if column not in frame]
    sparse_columns: list[str] = []

    for column in REQUIRED_HOURLY_COLUMNS:
        if column not in frame:
            continue
        valid_ratio = pd.to_numeric(frame[column], errors="coerce").notna().mean()
        if valid_ratio < minimum_coverage:
            sparse_columns.append(column)

    notes: list[str] = []
    if coverage < minimum_coverage:
        notes.append(f"Hourly coverage was {coverage:.0%} ({observed}/{expected} expected hours).")
    if missing_columns:
        notes.append(f"Missing required variables: {', '.join(missing_columns)}.")
    if sparse_columns:
        notes.append(f"Sparse required variables: {', '.join(sparse_columns)}.")
    if not notes:
        notes.append(f"Data completeness check passed with {observed}/{expected} expected local-period hours.")

    return DataQualityReport(
        ok=coverage >= minimum_coverage and not missing_columns and not sparse_columns,
        expected_hours=expected,
        observed_hours=observed,
        coverage=float(coverage),
        missing_columns=missing_columns,
        sparse_columns=sparse_columns,
        notes=notes,
    )


def validate_hourly_week(
    frame: pd.DataFrame,
    start: date,
    end: date,
    timezone_name: str,
    minimum_coverage: float = 0.95,
) -> DataQualityReport:
    """Backward-compatible wrapper around period validation."""
    return validate_hourly_period(frame, start, end, timezone_name, minimum_coverage)
