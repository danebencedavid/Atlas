"""Durable record of builds that were withheld rather than published.

When observations fall short of the reporting window the build refuses to
publish, which is correct: a thin edition presented as a whole one is worse than
no new edition. But refusing is invisible to a reader. The deployment simply
keeps serving the previous edition, and nothing on the page says a newer one was
attempted and rejected.

So a withheld build leaves a record here, and the next edition that does publish
carries a notice naming what was withheld and why. The record is committed
because CI runners are ephemeral: without that, the evidence of a withheld build
dies with the runner that withheld it.
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


def status_path(config: AtlasConfig) -> Path:
    return config.outputs.reports_dir / "status" / STATUS_FILENAME


def read_withheld(config: AtlasConfig) -> list[WithheldBuild]:
    path = status_path(config)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload["withheld"]
        if not isinstance(entries, list):
            raise TypeError("'withheld' must be a list")
        return [WithheldBuild(**entry) for entry in entries]
    except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as exc:
        raise WithheldStatusError(
            f"Cannot verify the withheld-build record at {path}; publication is blocked."
        ) from exc


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
    existing = read_withheld(config)
    # One entry per window: repeated failures on the same day are one story, and
    # a daily retry would otherwise bury the record in duplicates.
    kept = [item for item in existing if (item.period_start, item.period_end) != (entry.period_start, entry.period_end)]
    path = status_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_status(path, [*kept, entry])
    return entry


def _write_status(path: Path, entries: list[WithheldBuild]) -> None:
    """Replace the status record atomically so interruption leaves the old truth."""
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps({"withheld": [asdict(item) for item in entries]}, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def clear_withheld(config: AtlasConfig) -> None:
    """Drop the record once an edition publishes and carries the notice."""
    path = status_path(config)
    if path.is_file():
        _write_status(path, [])
