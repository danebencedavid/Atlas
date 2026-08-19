"""Forecast archive built on the Open-Meteo Previous Runs API.

Training data for bias correction must contain only what was knowable before the
valid time. The Previous Runs API provides exactly that: ``temperature_2m_previous_day1``
is the value a model predicted 24 hours before it verified, ``_previous_day2`` 48
hours before, and so on.

The Historical Forecast API is deliberately *not* used here. It stitches together
the earliest hours of successive model runs, so every value carries information
from a run issued close to the valid time. A model trained on it would learn from
data unavailable at inference and score far better than it could in practice.
That is look-ahead bias, and it is silent. If a future change needs forecast
features, it must come through this module, not through
``historical-forecast-api.open-meteo.com``.

Two collectors share one schema and one store:

``backfill``  pulls the Previous Runs history in two-week chunks.
``live``      appends forecasts as they are issued, because Previous Runs caps at
              seven daily offsets and does not preserve full run structure.

Both are append-only. A stored forecast is never rewritten, because rewriting one
would destroy the record of what was actually predicted at the time.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from atlas.config import AtlasConfig
from atlas.ingest import fetch_json_with_retry

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo is CC BY 4.0 and requires credit, a licence link, and a statement
# that changes were made. Bias correction modifies the values, so every surface
# built from this archive must carry it.
ATTRIBUTION = (
    "Forecast data from Open-Meteo.com, licensed CC BY 4.0 "
    "(https://creativecommons.org/licenses/by/4.0/). Values are modified: they are "
    "paired with station observations and statistically bias-corrected by Atlas."
)

# The one schema both collectors write.
SCHEMA: dict[str, str] = {
    "valid_time_utc": "datetime64[ns, UTC]",
    "lead_time_hours": "int16",
    "model": "string",
    "variable": "string",
    "value": "float32",
    "retrieved_at": "datetime64[ns, UTC]",
}

# Requested in metres per second so the archive matches the rest of the repo.
WIND_VARIABLES = {"wind_speed_10m", "wind_gusts_10m"}


@dataclass
class CallBudget:
    """Running count of API calls, logged as the brief requires.

    Limits are 10,000/day, 5,000/hour and 600/minute. A conservative delay between
    requests keeps the per-minute figure far below the ceiling; the counters exist
    so a long backfill can report what it actually spent.
    """

    calls: int = 0
    cache_hits: int = 0
    delay_seconds: float = 1.2
    daily_limit: int = 10_000
    log: list[str] = field(default_factory=list)

    def record_call(self, label: str) -> None:
        self.calls += 1
        self.log.append(f"call {self.calls}: {label}")
        if self.calls > self.daily_limit:
            raise RuntimeError(
                f"Refusing to exceed the {self.daily_limit} calls/day limit "
                f"(would be call {self.calls})."
            )

    def record_cache_hit(self) -> None:
        self.cache_hits += 1

    def wait(self) -> None:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

    def summary(self) -> str:
        total = self.calls + self.cache_hits
        served = (self.cache_hits / total * 100.0) if total else 0.0
        return (
            f"{self.calls} API calls, {self.cache_hits} served from cache "
            f"({served:.0f}% cached)"
        )


def _cache_path(config: AtlasConfig, label: str) -> Path:
    return config.outputs.data_dir / "raw" / "previous_runs" / f"{label}.json"


def _cached_json(
    config: AtlasConfig,
    label: str,
    url: str,
    params: dict[str, Any],
    budget: CallBudget,
    refresh: bool = False,
) -> dict[str, Any]:
    """Every response lands on disk before anything reads it.

    Re-runs, retries and iteration must cost nothing, because this code is
    expected to run dozens of times during development.
    """
    path = _cache_path(config, label)
    if path.exists() and not refresh:
        budget.record_cache_hit()
        return json.loads(path.read_text(encoding="utf-8"))
    budget.wait()
    payload = fetch_json_with_retry(url, params)
    budget.record_call(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def chunk_dates(start: date, end: date, days: int) -> list[tuple[date, date]]:
    """Split a span into inclusive windows of at most ``days`` days."""
    if end < start:
        return []
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=days - 1), end)
        windows.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return windows


def batch_variables(variables: Iterable[str], size: int) -> list[list[str]]:
    """Group variables so no request carries more than ``size`` of them."""
    ordered = list(variables)
    return [ordered[index : index + size] for index in range(0, len(ordered), size)]


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame({name: pd.Series(dtype=dtype) for name, dtype in SCHEMA.items()})


def _conform(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the declared schema, so every writer produces identical columns."""
    if frame.empty:
        return _empty_frame()
    out = frame.loc[:, list(SCHEMA)].copy()
    for name, dtype in SCHEMA.items():
        out[name] = out[name].astype(dtype)
    return out.sort_values(["valid_time_utc", "model", "variable", "lead_time_hours"]).reset_index(
        drop=True
    )


def _parse_previous_runs(
    payload: dict[str, Any],
    variables: list[str],
    lead_days: list[int],
    models: list[str],
    retrieved_at: datetime,
) -> pd.DataFrame:
    """Melt an Open-Meteo response into the long schema.

    Response keys take the form ``<variable>_previous_day<N>`` and, when more than
    one model is requested, gain a ``_<model>`` suffix.
    """
    hourly = payload.get("hourly") or {}
    if "time" not in hourly:
        return _empty_frame()
    times = pd.to_datetime(hourly["time"], utc=True)
    rows: list[pd.DataFrame] = []
    multi_model = len(models) > 1
    for variable in variables:
        for lead in lead_days:
            for model in models:
                key = f"{variable}_previous_day{lead}"
                if multi_model:
                    key = f"{key}_{model}"
                series = hourly.get(key)
                if series is None:
                    continue
                rows.append(
                    pd.DataFrame(
                        {
                            "valid_time_utc": times,
                            "lead_time_hours": lead * 24,
                            "model": model,
                            "variable": variable,
                            "value": pd.to_numeric(pd.Series(series), errors="coerce"),
                            "retrieved_at": retrieved_at,
                        }
                    )
                )
    if not rows:
        return _empty_frame()
    frame = pd.concat(rows, ignore_index=True)
    # A null here means the model did not carry that variable at that offset;
    # keeping the row would inflate every later sample count.
    frame = frame.dropna(subset=["value"])
    return _conform(frame)


def fetch_previous_runs_window(
    config: AtlasConfig,
    start: date,
    end: date,
    variables: list[str],
    budget: CallBudget,
    refresh: bool = False,
) -> pd.DataFrame:
    """Fetch one window of Previous Runs data for the configured leads and models."""
    settings = config.forecast_archive
    requested = [
        f"{variable}_previous_day{lead}" for variable in variables for lead in settings.lead_days
    ]
    label = (
        f"prevruns_{start.isoformat()}_{end.isoformat()}"
        f"_{'-'.join(variables)}_{'-'.join(str(d) for d in settings.lead_days)}"
        f"_{'-'.join(settings.models)}"
    )
    params: dict[str, Any] = {
        "latitude": config.location.latitude,
        "longitude": config.location.longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(requested),
        # Everything internal is UTC; local time is a presentation concern only.
        "timezone": "UTC",
        "models": ",".join(settings.models),
    }
    if any(variable in WIND_VARIABLES for variable in variables):
        params["wind_speed_unit"] = "ms"
    payload = _cached_json(config, label, PREVIOUS_RUNS_URL, params, budget, refresh=refresh)
    return _parse_previous_runs(
        payload,
        variables,
        settings.lead_days,
        settings.models,
        datetime.now(timezone.utc),
    )


def backfill_previous_runs(
    config: AtlasConfig,
    start: date | None = None,
    end: date | None = None,
    budget: CallBudget | None = None,
    refresh: bool = False,
    progress: bool = True,
) -> tuple[pd.DataFrame, CallBudget]:
    """Pull the whole Previous Runs history in two-week, ten-variable requests."""
    settings = config.forecast_archive
    budget = budget or CallBudget(delay_seconds=settings.request_delay_seconds)
    start = start or date.fromisoformat(settings.start_date)
    end = end or (datetime.now(timezone.utc).date() - timedelta(days=1))

    windows = chunk_dates(start, end, settings.chunk_days)
    # Leads multiply the requested keys, so the batch size is the variable budget
    # divided by the number of offsets rather than the raw ten.
    per_request = max(1, settings.max_variables_per_request // max(1, len(settings.lead_days)))
    batches = batch_variables(settings.variables, per_request)

    collected: list[pd.DataFrame] = []
    total = len(windows) * len(batches)
    done = 0
    for window_start, window_end in windows:
        for variables in batches:
            frame = fetch_previous_runs_window(
                config, window_start, window_end, variables, budget, refresh=refresh
            )
            if not frame.empty:
                collected.append(frame)
            done += 1
            if progress and done % 25 == 0:
                print(f"  {done}/{total} requests, {budget.summary()}", flush=True)
    if not collected:
        return _empty_frame(), budget
    return _conform(pd.concat(collected, ignore_index=True)), budget


def _parse_live_forecast(
    payload: dict[str, Any],
    variables: list[str],
    models: list[str],
    issued_at: datetime,
) -> pd.DataFrame:
    """Melt a live forecast response, deriving lead time from the issue time."""
    hourly = payload.get("hourly") or {}
    if "time" not in hourly:
        return _empty_frame()
    times = pd.to_datetime(hourly["time"], utc=True)
    lead_hours = ((times - pd.Timestamp(issued_at)).total_seconds() / 3600.0).round().astype(int)
    rows: list[pd.DataFrame] = []
    multi_model = len(models) > 1
    for variable in variables:
        for model in models:
            key = f"{variable}_{model}" if multi_model else variable
            series = hourly.get(key)
            if series is None:
                continue
            rows.append(
                pd.DataFrame(
                    {
                        "valid_time_utc": times,
                        "lead_time_hours": lead_hours,
                        "model": model,
                        "variable": variable,
                        "value": pd.to_numeric(pd.Series(series), errors="coerce"),
                        "retrieved_at": issued_at,
                    }
                )
            )
    if not rows:
        return _empty_frame()
    frame = pd.concat(rows, ignore_index=True)
    frame = frame.dropna(subset=["value"])
    # Only future-valid hours are forecasts; the API also returns the current hour
    # and, depending on the model, a little past data.
    frame = frame[frame["lead_time_hours"] >= 0]
    return _conform(frame)


def fetch_live_forecast(
    config: AtlasConfig,
    budget: CallBudget | None = None,
    forecast_days: int = 4,
    refresh: bool = False,
) -> tuple[pd.DataFrame, CallBudget]:
    """Capture the forecast as issued now, for the record Previous Runs cannot keep."""
    settings = config.forecast_archive
    budget = budget or CallBudget(delay_seconds=settings.request_delay_seconds)
    issued_at = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    label = f"live_{issued_at.strftime('%Y%m%dT%H')}"
    params: dict[str, Any] = {
        "latitude": config.location.latitude,
        "longitude": config.location.longitude,
        "hourly": ",".join(settings.variables),
        "forecast_days": forecast_days,
        "timezone": "UTC",
        "models": ",".join(settings.models),
        "wind_speed_unit": "ms",
    }
    payload = _cached_json(config, label, FORECAST_URL, params, budget, refresh=refresh)
    return _parse_live_forecast(payload, settings.variables, settings.models, issued_at), budget


def archive_path(config: AtlasConfig, kind: str, period: str) -> Path:
    return config.forecast_archive.archive_dir / kind / f"{period}.parquet"


def write_archive(config: AtlasConfig, frame: pd.DataFrame, kind: str) -> list[Path]:
    """Write the frame to Parquet, partitioned by valid month, append-only.

    Existing rows are never replaced. A forecast already on disk is the record of
    what was predicted at that time; re-running the collector must not rewrite it.
    Deduplication is on the full key, so a repeated fetch is a no-op.
    """
    if frame.empty:
        return []
    frame = _conform(frame)
    written: list[Path] = []
    for period, group in frame.groupby(frame["valid_time_utc"].dt.strftime("%Y-%m"), sort=True):
        path = archive_path(config, kind, str(period))
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pd.read_parquet(path)
            group = pd.concat([existing, group], ignore_index=True)
        group = _conform(group).drop_duplicates(
            subset=["valid_time_utc", "lead_time_hours", "model", "variable", "retrieved_at"],
            keep="first",
        )
        group.to_parquet(path, index=False)
        written.append(path)
    return written


def read_archive(config: AtlasConfig, kind: str | None = None) -> pd.DataFrame:
    """Read the stored archive back, optionally limited to one collector."""
    root = config.forecast_archive.archive_dir
    if not root.exists():
        return _empty_frame()
    kinds = [kind] if kind else [child.name for child in root.iterdir() if child.is_dir()]
    frames: list[pd.DataFrame] = []
    for name in kinds:
        for path in sorted((root / name).glob("*.parquet")):
            frames.append(pd.read_parquet(path))
    if not frames:
        return _empty_frame()
    return _conform(pd.concat(frames, ignore_index=True))


def availability_report(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows actually retrieved per variable, lead time and model.

    The brief asks what is retrievable before pulling everything; this is the
    answer after the fact, and the check that nothing silently went missing.
    """
    if frame.empty:
        return pd.DataFrame(columns=["variable", "lead_time_hours", "model", "rows", "first", "last"])
    grouped = (
        frame.groupby(["variable", "lead_time_hours", "model"], observed=True)
        .agg(rows=("value", "size"), first=("valid_time_utc", "min"), last=("valid_time_utc", "max"))
        .reset_index()
    )
    return grouped.sort_values(["variable", "lead_time_hours", "model"]).reset_index(drop=True)
