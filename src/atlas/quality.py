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


@dataclass(frozen=True)
class InputCoverage:
    """Completeness of one observational input over the reporting window.

    ``available`` is distinct from a zero count. A source that failed and a source
    that genuinely observed nothing must never be presented the same way.
    """

    name: str
    available: bool
    observed: int
    expected: int
    threshold: float
    ok: bool
    per_day: pd.DataFrame
    structural_note: str | None
    notes: list[str]

    @property
    def coverage(self) -> float:
        return self.observed / self.expected if self.expected else 0.0


class ObservationFreshnessError(RuntimeError):
    """Raised when retrieved observations stop short of the window end."""


class PublicationIntegrityError(RuntimeError):
    """Raised when a required input cannot support a complete publication."""


def assert_required_input_coverage(
    coverages: list[InputCoverage],
    required: tuple[str, ...] = ("station",),
) -> None:
    """Fail closed when a required source misses its completeness threshold.

    Radar, lightning and the other contextual feeds remain optional: their
    absence is disclosed in the edition instead of being converted into a
    reassuring zero. The station ledger is different because its measurements
    support headline values and the objective event record.
    """
    by_name = {coverage.name: coverage for coverage in coverages}
    failures: list[str] = []
    for name in required:
        coverage = by_name.get(name)
        if coverage is None:
            failures.append(f"Required {name} coverage was not evaluated.")
        elif not coverage.ok:
            detail = " ".join(note.strip() for note in coverage.notes if note.strip())
            failures.append(detail or f"Required {name} coverage did not pass.")
    if failures:
        raise PublicationIntegrityError(" ".join(failures))


def _per_day_coverage(
    times: pd.Series,
    start: date,
    end: date,
    timezone_name: str,
    interval_minutes: int,
) -> pd.DataFrame:
    """Coverage for each local day, so a thin trailing day cannot hide in an average."""
    days = pd.date_range(start, end, freq="D")
    counts = {day.date(): 0 for day in days}
    expected = {}
    for day in counts:
        day_start, day_end = local_period_to_utc_bounds(day, day, timezone_name)
        expected[day] = int(
            (day_end - day_start).total_seconds() / (interval_minutes * 60)
        )
    if len(times):
        local = pd.to_datetime(times, utc=True).dt.tz_convert(timezone_name).dt.date
        for day, count in local.value_counts().items():
            if day in counts:
                counts[day] = int(count)
    frame = pd.DataFrame(
        {
            "local_day": list(counts),
            "observed": list(counts.values()),
            "expected": [expected[day] for day in counts],
        }
    )
    frame["coverage"] = frame["observed"] / frame["expected"]
    return frame


def validate_station_period(
    station,
    start: date,
    end: date,
    timezone_name: str,
    minimum_coverage: float = 0.95,
    interval_minutes: int = 10,
) -> InputCoverage:
    """Gate the station record, per day as well as in total."""
    utc_start, utc_end = local_period_to_utc_bounds(start, end, timezone_name)
    expected = int((utc_end - utc_start).total_seconds() / (interval_minutes * 60))
    frame = getattr(station, "frame", pd.DataFrame())
    available = not frame.empty
    times = frame["time"] if available and "time" in frame else pd.Series(dtype="datetime64[ns, UTC]")
    times = pd.to_datetime(times, utc=True).drop_duplicates()
    times = times[(times >= utc_start) & (times < utc_end)]
    observed = int(len(times))
    available = observed > 0
    per_day = _per_day_coverage(times, start, end, timezone_name, interval_minutes)

    notes: list[str] = []
    coverage = observed / expected if expected else 0.0
    if not available:
        notes.append("Station observations were unavailable for this period.")
    else:
        thin = per_day[per_day["coverage"] < minimum_coverage]
        if coverage < minimum_coverage:
            notes.append(
                f"Station coverage {observed}/{expected} ({coverage:.0%}) is below the "
                f"{minimum_coverage:.0%} threshold."
            )
        if not thin.empty:
            notes.append(
                f"{len(thin)} local day(s) are below the {minimum_coverage:.0%} "
                "station threshold:"
            )
        for row in thin.itertuples():
            notes.append(
                f"  {row.local_day}: {row.observed}/{row.expected} ({row.coverage:.0%})."
            )
    every_day_ok = bool(len(per_day)) and bool(
        (per_day["coverage"] >= minimum_coverage).all()
    )
    return InputCoverage(
        name="station",
        available=available,
        observed=observed,
        expected=expected,
        threshold=minimum_coverage,
        ok=available and coverage >= minimum_coverage and every_day_ok,
        per_day=per_day,
        structural_note=None,
        notes=notes,
    )


def validate_radar_period(
    radar,
    start: date,
    end: date,
    timezone_name: str,
    minimum_coverage: float = 0.90,
    interval_minutes: int = 30,
    retention_hours: float = 71.0,
    now: pd.Timestamp | None = None,
) -> InputCoverage:
    """Gate the radar archive against what the provider still retains.

    The composite archive keeps roughly ``retention_hours`` of frames against a
    72-hour window, so the oldest part of the window is structurally unavailable.
    Gating on the full window would fail every build for a known provider limit,
    so the threshold applies to what is actually reachable and the shortfall is
    disclosed instead.
    """
    utc_start, utc_end = local_period_to_utc_bounds(start, end, timezone_name)
    now = now or pd.Timestamp.now(tz="UTC")
    reachable_start = max(utc_start, now - pd.Timedelta(hours=retention_hours))
    window_frames = int((utc_end - utc_start).total_seconds() / (interval_minutes * 60))
    expected = max(
        0, int((utc_end - reachable_start).total_seconds() / (interval_minutes * 60))
    )
    times = pd.Series(getattr(radar, "times", []) or [], dtype="object")
    times = pd.to_datetime(times, utc=True) if len(times) else pd.Series(dtype="datetime64[ns, UTC]")
    observed = int(len(times))
    available = observed > 0
    per_day = _per_day_coverage(times, start, end, timezone_name, interval_minutes)

    structural_note = None
    if expected < window_frames:
        missing = window_frames - expected
        structural_note = (
            f"The radar archive retains about {retention_hours:.0f} hours, so the oldest "
            f"{missing} frame(s) of this {window_frames}-frame window are structurally "
            "unavailable rather than missing."
        )
    coverage = observed / expected if expected else 0.0
    notes: list[str] = []
    if structural_note:
        notes.append(structural_note)
    if not available:
        notes.append("Radar frames were unavailable for this period.")
    elif coverage < minimum_coverage:
        notes.append(
            f"Radar coverage {observed}/{expected} ({coverage:.0%}) of the reachable window "
            f"is below the {minimum_coverage:.0%} threshold."
        )
    return InputCoverage(
        name="radar",
        available=available,
        observed=observed,
        expected=expected,
        threshold=minimum_coverage,
        ok=available and coverage >= minimum_coverage,
        per_day=per_day,
        structural_note=structural_note,
        notes=notes,
    )


def validate_lightning_period(lightning, start: date, end: date, timezone_name: str) -> InputCoverage:
    """Separate a failed lightning archive from a genuinely quiet period.

    There is no coverage ratio to compute: zero strikes is a valid observation.
    The only question that matters is whether the archive answered at all.
    """
    available = bool(getattr(lightning, "available", True))
    frame = getattr(lightning, "frame", pd.DataFrame())
    observed = int(len(frame))
    missing_days = int(getattr(lightning, "missing_days", 0))
    notes: list[str] = []
    if not available:
        notes.append(
            "Lightning archive was unavailable; this is not a report of zero strikes."
        )
    elif observed == 0:
        notes.append("Lightning archive was read successfully and recorded no strikes in range.")
    if available and missing_days:
        notes.append(f"{missing_days} daily lightning file(s) were unavailable within the period.")
    return InputCoverage(
        name="lightning",
        available=available,
        observed=observed,
        expected=0,
        threshold=0.0,
        ok=available,
        per_day=pd.DataFrame(columns=["local_day", "observed", "expected", "coverage"]),
        structural_note=None,
        notes=notes,
    )


def observation_shortfall_hours(
    latest: pd.Timestamp | None,
    start: date,
    end: date,
    timezone_name: str,
) -> float:
    """Hours by which the newest observation falls short of the window end."""
    _, utc_end = local_period_to_utc_bounds(start, end, timezone_name)
    if latest is None or pd.isna(latest):
        return float((utc_end - pd.Timestamp(utc_end).tz_convert("UTC")).total_seconds()) or float("inf")
    latest = pd.Timestamp(latest)
    if latest.tzinfo is None:
        raise AssertionError("Observation timestamps must be timezone-aware UTC.")
    shortfall = (pd.Timestamp(utc_end) - latest).total_seconds() / 3600.0
    return max(0.0, float(shortfall))


def assert_observations_fresh(
    latest: pd.Timestamp | None,
    start: date,
    end: date,
    timezone_name: str,
    label: str = "station",
    tolerance_hours: float = 2.0,
) -> float:
    """Fail loudly when the retrieved record stops short of the window end.

    This, not the build schedule, is what guarantees the window is observed. The
    cron time is only an optimisation that makes the check likely to pass: the
    provider controls when its file regenerates and can change it without notice,
    so the assertion has to be on the data actually retrieved.
    """
    if latest is None or (isinstance(latest, float) and pd.isna(latest)):
        raise ObservationFreshnessError(
            f"No {label} observations were retrieved for {start}..{end}; the window end "
            "cannot be confirmed as observed."
        )
    shortfall = observation_shortfall_hours(latest, start, end, timezone_name)
    if shortfall > tolerance_hours:
        _, utc_end = local_period_to_utc_bounds(start, end, timezone_name)
        raise ObservationFreshnessError(
            f"The {label} record ends {shortfall:.1f} h before the reporting window closes "
            f"(newest {pd.Timestamp(latest):%Y-%m-%d %H:%M} UTC, window end "
            f"{utc_end:%Y-%m-%d %H:%M} UTC, tolerance {tolerance_hours:.1f} h). "
            "The provider file has probably not regenerated yet; rerun after it does."
        )
    return shortfall


def validate_hourly_week(
    frame: pd.DataFrame,
    start: date,
    end: date,
    timezone_name: str,
    minimum_coverage: float = 0.95,
) -> DataQualityReport:
    """Backward-compatible wrapper around period validation."""
    return validate_hourly_period(frame, start, end, timezone_name, minimum_coverage)
