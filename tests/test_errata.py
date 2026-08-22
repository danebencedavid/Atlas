from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from atlas.errata import (
    MARKER,
    annotate_daily_from_periods,
    annotate_edition,
    measure_edition,
)

PAGE = (
    "<!doctype html><html><body><div class='app-shell'>"
    "<header class='report-topbar'></header><main><p>content</p></main>"
    "</body></html>"
)


def _edition(tmp_path: Path, name: str, last: str, pages: int = 2) -> Path:
    """A saved edition whose station record stops at ``last``."""
    directory = tmp_path / name
    (directory / "data").mkdir(parents=True)
    start_text, end_text = name.split("_")
    times = pd.date_range(
        pd.Timestamp(f"{start_text} 00:00", tz="Europe/Budapest").tz_convert("UTC"),
        pd.Timestamp(last, tz="UTC"),
        freq="10min",
        inclusive="left",
    )
    pd.DataFrame({"time": times}).to_csv(directory / "data" / "hungaromet_station_observations.csv", index=False)
    for index in range(pages):
        (directory / f"page{index}.html").write_text(PAGE, encoding="utf-8")
    return directory


def test_coverage_is_recomputed_from_the_edition_s_own_observations(tmp_path):
    # Stops at the end of the second local day, leaving the third unobserved.
    directory = _edition(tmp_path, "2026-08-14_2026-08-16", "2026-08-15 22:00")
    coverage = measure_edition(directory)
    assert coverage is not None
    assert coverage.observed == 288
    assert coverage.expected == 432
    assert coverage.final_day_observed == 0
    assert coverage.defective


def test_a_fully_observed_edition_is_not_annotated(tmp_path):
    directory = _edition(tmp_path, "2026-08-14_2026-08-16", "2026-08-16 22:00")
    coverage = measure_edition(directory)
    assert not coverage.defective
    assert annotate_edition(directory, date(2026, 8, 19)) == 0
    assert MARKER not in (directory / "page0.html").read_text(encoding="utf-8")


def test_the_banner_states_the_figures_and_precedes_the_content(tmp_path):
    directory = _edition(tmp_path, "2026-08-14_2026-08-16", "2026-08-15 22:00")
    assert annotate_edition(directory, date(2026, 8, 19)) == 2
    text = (directory / "page0.html").read_text(encoding="utf-8")
    assert MARKER in text
    assert "Erratum, issued 2026-08-19" in text
    assert "288/432" in text
    assert "0/144" in text
    # Visible above the edition rather than buried at the end of it.
    assert text.index(MARKER) < text.index("<main>")


def test_annotating_twice_does_not_stack_banners(tmp_path):
    directory = _edition(tmp_path, "2026-08-14_2026-08-16", "2026-08-15 22:00")
    annotate_edition(directory, date(2026, 8, 19))
    annotate_edition(directory, date(2026, 8, 20))
    text = (directory / "page0.html").read_text(encoding="utf-8")
    assert text.count(MARKER) == 1
    # The refreshed date replaces the old one rather than sitting beside it.
    assert "2026-08-20" in text
    assert "2026-08-19" not in text


def test_an_edition_without_observations_is_skipped(tmp_path):
    directory = tmp_path / "2026-08-14_2026-08-16"
    (directory / "data").mkdir(parents=True)
    (directory / "page0.html").write_text(PAGE, encoding="utf-8")
    assert measure_edition(directory) is None
    assert annotate_edition(directory, date(2026, 8, 19)) == 0


def test_daily_edition_inherits_reproducible_erratum_from_its_period(tmp_path):
    periods = tmp_path / "periods"
    daily = tmp_path / "daily"
    _edition(periods, "2026-08-14_2026-08-16", "2026-08-15 22:00")
    daily_page = daily / "2026-08-16"
    daily_page.mkdir(parents=True)
    (daily_page / "index.html").write_text(PAGE, encoding="utf-8")
    unaffected = daily / "2026-08-15"
    unaffected.mkdir()
    (unaffected / "index.html").write_text(PAGE, encoding="utf-8")

    result = annotate_daily_from_periods(daily, periods, date(2026, 8, 19))

    assert result == {"2026-08-16": 1}
    corrected = (daily_page / "index.html").read_text(encoding="utf-8")
    assert MARKER in corrected
    assert "288/432" in corrected
    assert "0/144" in corrected
    assert MARKER not in (unaffected / "index.html").read_text(encoding="utf-8")
