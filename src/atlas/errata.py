"""Annotate saved editions whose observational coverage was incomplete.

Editions published before the observational quality gate existed were built from
a station record that stopped short of their own window end, because the build
ran hours before the provider regenerated its export. Those editions are dated
artefacts: they are annotated, never regenerated, because rewriting a published
edition would destroy the record of what was actually said on the day.

Coverage is recomputed from each edition's own committed observation file, so
every figure in a banner is reproducible from the edition it describes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

MARKER = "data-atlas-erratum"
STATION_INTERVAL_MINUTES = 10
DEFAULT_TIMEZONE = "Europe/Budapest"

# Products computed from the station record over the whole window, and therefore
# computed over a window whose final day was largely unobserved.
AFFECTED_PRODUCTS = (
    "objective frontal passage detection, which reads the station series directly",
    "the objective phenomena ledger, which draws on station, radar and lightning",
    "the period mean temperature, precipitation total and maximum gust in the "
    "station observation ledger",
)


@dataclass(frozen=True)
class EditionCoverage:
    edition: str
    start: date
    end: date
    observed: int
    expected: int
    final_day_observed: int
    final_day_expected: int

    @property
    def coverage(self) -> float:
        return self.observed / self.expected if self.expected else 0.0

    @property
    def final_day_coverage(self) -> float:
        return self.final_day_observed / self.final_day_expected if self.final_day_expected else 0.0

    @property
    def defective(self) -> bool:
        # A fully observed edition needs no annotation.
        return self.final_day_coverage < 0.95


def measure_edition(directory: Path, timezone_name: str = DEFAULT_TIMEZONE) -> EditionCoverage | None:
    """Recompute station coverage from an edition's own committed observations."""
    observations = directory / "data" / "hungaromet_station_observations.csv"
    if not observations.is_file():
        return None
    try:
        start_text, end_text = directory.name.split("_")
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
    except ValueError:
        return None
    frame = pd.read_csv(observations)
    if "time" not in frame:
        return None
    times = pd.to_datetime(frame["time"], utc=True)
    per_day_expected = int(24 * 60 / STATION_INTERVAL_MINUTES)
    days = len(pd.date_range(start, end, freq="D"))
    local_days = times.dt.tz_convert(ZoneInfo(timezone_name)).dt.date
    return EditionCoverage(
        edition=directory.name,
        start=start,
        end=end,
        observed=int(len(times)),
        expected=per_day_expected * days,
        final_day_observed=int((local_days == end).sum()),
        final_day_expected=per_day_expected,
    )


def erratum_html(coverage: EditionCoverage, issued: date) -> str:
    products = "".join(f"<li>{product}</li>" for product in AFFECTED_PRODUCTS)
    return (
        f'<div class="edition-notice" role="note" {MARKER}="{issued.isoformat()}">'
        f"<strong>Erratum, issued {issued.isoformat()}.</strong> "
        f"This edition was published with incomplete station observations. It achieved "
        f"{coverage.observed}/{coverage.expected} ten-minute records "
        f"({coverage.coverage:.0%}) across its window, and its final day, "
        f"{coverage.end.isoformat()}, carried only {coverage.final_day_observed}/"
        f"{coverage.final_day_expected} records ({coverage.final_day_coverage:.0%}). "
        f"The build ran before the provider regenerated its daily export, so the last "
        f"{(1 - coverage.final_day_coverage) * 24:.0f} hours of the window were unobserved "
        f"at the time of writing. Quantities derived from the station record over the whole "
        f"window are affected, in particular:<ul>{products}</ul>"
        f"Gridded quantities are unaffected: the hourly analysis was complete. This edition "
        f"is annotated rather than regenerated, so it still shows what was published on the day."
        f"</div>"
    )


def annotate_edition(directory: Path, issued: date, timezone_name: str = DEFAULT_TIMEZONE) -> int:
    """Insert the erratum into every page of one edition. Idempotent."""
    coverage = measure_edition(directory, timezone_name)
    if coverage is None or not coverage.defective:
        return 0
    banner = erratum_html(coverage, issued)
    touched = 0
    for page in sorted(directory.rglob("*.html")):
        text = page.read_text(encoding="utf-8", errors="replace")
        if MARKER in text:
            # Refresh rather than stack a second banner on a re-run.
            text = re.sub(
                rf'<div class="edition-notice" role="note" {MARKER}=.*?</div>\s*(?=<main)',
                "",
                text,
                flags=re.S,
            )
        if "<main>" not in text:
            continue
        page.write_text(text.replace("<main>", f"{banner}<main>", 1), encoding="utf-8")
        touched += 1
    return touched


def annotate_all(reports_dir: Path, issued: date, timezone_name: str = DEFAULT_TIMEZONE) -> dict[str, int]:
    results: dict[str, int] = {}
    for child in sorted(reports_dir.iterdir()):
        if not child.is_dir():
            continue
        touched = annotate_edition(child, issued, timezone_name)
        if touched:
            results[child.name] = touched
    return results


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Annotate editions with incomplete observations.")
    parser.add_argument("--reports", default="reports/periods")
    parser.add_argument("--issued", default=date.today().isoformat())
    args = parser.parse_args()
    results = annotate_all(Path(args.reports), date.fromisoformat(args.issued))
    for edition, pages in results.items():
        coverage = measure_edition(Path(args.reports) / edition)
        print(
            f"{edition}: annotated {pages} page(s); "
            f"{coverage.observed}/{coverage.expected} ({coverage.coverage:.0%}), "
            f"final day {coverage.final_day_coverage:.0%}"
        )
    if not results:
        print("No edition required annotation.")


if __name__ == "__main__":
    main()
