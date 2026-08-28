"""Durable record of publication attempts that were withheld and recovered.

When observations fall short of the reporting window the build refuses to
publish, which is correct: a thin edition presented as a whole one is worse than
no new edition. But refusing is invisible to a reader. The deployment simply
keeps serving the previous edition, and nothing on the page says a newer one was
attempted and rejected.

So a withheld build leaves a pending record here. A successful rerun of the same
window moves it to the recovered ledger with final station coverage and evidence
links. The record is committed because CI runners are ephemeral: without that,
the evidence of both the failure and its recovery dies with the runner.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from atlas.config import AtlasConfig

STATUS_FILENAME = "withheld.json"


class WithheldStatusError(RuntimeError):
    """Raised when the publication-status record cannot be trusted."""


@dataclass(frozen=True)
class WithheldBuild:
    attempted_at: str
    period_start: str
    period_end: str
    reason: str
    shortfall_hours: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("attempted_at", "period_start", "period_end", "reason"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise TypeError(f"{field_name} must be a non-empty string")
        attempted = datetime.fromisoformat(self.attempted_at.replace("Z", "+00:00"))
        if attempted.tzinfo is None:
            raise ValueError("attempted_at must include a timezone")
        period_start = date.fromisoformat(self.period_start)
        period_end = date.fromisoformat(self.period_end)
        if period_end < period_start:
            raise ValueError("period_end must not precede period_start")
        if self.shortfall_hours is not None and not isinstance(
            self.shortfall_hours, (int, float)
        ):
            raise TypeError("shortfall_hours must be numeric or null")

    def describe(self) -> str:
        window = f"{self.period_start} to {self.period_end}"
        stamp = self.attempted_at[:16].replace("T", " ")
        if self.shortfall_hours is not None:
            return (
                f"The edition for {window} was withheld on {stamp} UTC: observations ended "
                f"{self.shortfall_hours:.1f} h before the window closed."
            )
        return f"The edition for {window} was withheld on {stamp} UTC: {self.reason}"


@dataclass(frozen=True)
class RecoveredBuild:
    attempted_at: str
    period_start: str
    period_end: str
    reason: str
    recovered_at: str
    station_observed: int
    station_expected: int
    report_url: str
    data_url: str
    workflow_url: str | None = None
    shortfall_hours: float | None = None

    def __post_init__(self) -> None:
        # Reuse the pending-record validation so the original incident remains
        # just as trustworthy after it moves into the recovery ledger.
        WithheldBuild(
            attempted_at=self.attempted_at,
            period_start=self.period_start,
            period_end=self.period_end,
            reason=self.reason,
            shortfall_hours=self.shortfall_hours,
        )
        recovered = datetime.fromisoformat(self.recovered_at.replace("Z", "+00:00"))
        if recovered.tzinfo is None:
            raise ValueError("recovered_at must include a timezone")
        if not isinstance(self.station_observed, int) or self.station_observed < 0:
            raise TypeError("station_observed must be a non-negative integer")
        if not isinstance(self.station_expected, int) or self.station_expected <= 0:
            raise TypeError("station_expected must be a positive integer")
        if self.station_observed > self.station_expected:
            raise ValueError("station_observed must not exceed station_expected")
        for field_name in ("report_url", "data_url"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.startswith(("https://", "http://")):
                raise ValueError(f"{field_name} must be an absolute HTTP(S) URL")
        if self.workflow_url is not None and (
            not isinstance(self.workflow_url, str)
            or not self.workflow_url.startswith(("https://", "http://"))
        ):
            raise ValueError("workflow_url must be null or an absolute HTTP(S) URL")

    def describe(self) -> str:
        attempted = self.attempted_at[:16].replace("T", " ")
        recovered = self.recovered_at[:16].replace("T", " ")
        cause = (
            "because observations were incomplete"
            if self.shortfall_hours is not None
            else "after a publication check did not pass"
        )
        return (
            f"An earlier publication attempt for {self.period_start} to {self.period_end} "
            f"was delayed on {attempted} UTC {cause}. "
            f"The edition was subsequently recovered on {recovered} UTC with "
            f"{self.station_observed}/{self.station_expected} station observations."
        )


def status_path(config: AtlasConfig) -> Path:
    return config.outputs.reports_dir / "status" / STATUS_FILENAME


def _read_status(config: AtlasConfig) -> tuple[list[WithheldBuild], list[RecoveredBuild]]:
    path = status_path(config)
    if not path.is_file():
        return [], []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload["withheld"]
        if not isinstance(entries, list):
            raise TypeError("'withheld' must be a list")
        recovered = payload.get("recovered", [])
        if not isinstance(recovered, list):
            raise TypeError("'recovered' must be a list")
        return (
            [WithheldBuild(**entry) for entry in entries],
            [RecoveredBuild(**entry) for entry in recovered],
        )
    except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as exc:
        raise WithheldStatusError(
            f"Cannot verify the withheld-build record at {path}; publication is blocked."
        ) from exc


def read_withheld(config: AtlasConfig) -> list[WithheldBuild]:
    return _read_status(config)[0]


def read_recovered(config: AtlasConfig) -> list[RecoveredBuild]:
    return _read_status(config)[1]


def record_withheld(
    config: AtlasConfig,
    start: date,
    end: date,
    reason: str,
    shortfall_hours: float | None = None,
) -> WithheldBuild:
    """Append a withheld attempt, keeping any earlier ones for the same window."""
    entry = WithheldBuild(
        attempted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        reason=reason,
        shortfall_hours=None if shortfall_hours is None else round(float(shortfall_hours), 2),
    )
    existing, recovered = _read_status(config)
    # One entry per window: repeated failures on the same day are one story, and
    # a daily retry would otherwise bury the record in duplicates.
    kept = [item for item in existing if (item.period_start, item.period_end) != (entry.period_start, entry.period_end)]
    path = status_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_status(path, [*kept, entry], recovered)
    return entry


def prepare_recoveries(
    entries: list[WithheldBuild],
    start: date,
    end: date,
    *,
    station_observed: int,
    station_expected: int,
    site_url: str,
    workflow_url: str | None = None,
    recovered_at: str | None = None,
) -> list[RecoveredBuild]:
    """Describe successful recovery of pending attempts for exactly this window."""

    recovered_at = recovered_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    base = site_url.rstrip("/")
    daily_root = f"{base}/archive/daily/{end.isoformat()}"
    matches = [
        entry
        for entry in entries
        if (entry.period_start, entry.period_end) == (start.isoformat(), end.isoformat())
    ]
    return [
        RecoveredBuild(
            **asdict(entry),
            recovered_at=recovered_at,
            station_observed=int(station_observed),
            station_expected=int(station_expected),
            report_url=f"{daily_root}/",
            data_url=f"{daily_root}/data/daily_station_observations.csv",
            workflow_url=workflow_url,
        )
        for entry in matches
    ]


def record_recovered(
    config: AtlasConfig,
    recoveries: list[RecoveredBuild],
) -> list[RecoveredBuild]:
    """Move successfully published attempts from pending to recovered history."""

    if not recoveries:
        return []
    pending, history = _read_status(config)
    recovered_keys = {
        (item.attempted_at, item.period_start, item.period_end) for item in recoveries
    }
    pending = [
        item
        for item in pending
        if (item.attempted_at, item.period_start, item.period_end) not in recovered_keys
    ]
    for recovery in recoveries:
        key = (recovery.attempted_at, recovery.period_start, recovery.period_end)
        history = [
            item
            for item in history
            if (item.attempted_at, item.period_start, item.period_end) != key
        ]
        history.append(recovery)
    path = status_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_status(path, pending, history[-100:])
    return recoveries


def _write_status(
    path: Path,
    entries: list[WithheldBuild],
    recovered: list[RecoveredBuild] | None = None,
) -> None:
    """Replace the status record atomically so interruption leaves the old truth."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    payload: dict[str, object] = {"withheld": [asdict(item) for item in entries]}
    if recovered:
        payload["recovered"] = [asdict(item) for item in recovered]
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def clear_withheld(config: AtlasConfig) -> None:
    """Clear pending attempts while preserving the recovery audit history."""
    path = status_path(config)
    if path.is_file():
        _, recovered = _read_status(config)
        _write_status(path, [], recovered)
