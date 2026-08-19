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


@dataclass(frozen=True)
class WithheldBuild:
    attempted_at: str
    period_start: str
    period_end: str
    reason: str
    shortfall_hours: float | None = None

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
    except (json.JSONDecodeError, OSError):
        return []
    return [WithheldBuild(**entry) for entry in payload.get("withheld", [])]


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
    path.write_text(
        json.dumps({"withheld": [asdict(item) for item in [*kept, entry]]}, indent=2),
        encoding="utf-8",
    )
    return entry


def clear_withheld(config: AtlasConfig) -> None:
    """Drop the record once an edition publishes and carries the notice."""
    path = status_path(config)
    if path.is_file():
        path.write_text(json.dumps({"withheld": []}, indent=2), encoding="utf-8")
