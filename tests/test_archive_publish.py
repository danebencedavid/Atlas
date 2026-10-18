from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.archive_publish import enforce_published_archive_limits
from atlas.archive_publish import PublishedArchiveBudgetError
from atlas.archive_publish import PublishedArchiveCapacityWarning
from atlas.archive_publish import PublishedArchiveLimits
from atlas.archive_publish import staged_directory


def test_staged_directory_commits_complete_tree(tmp_path: Path):
    target = tmp_path / "archive"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")

    with staged_directory(target) as staging:
        (staging / "new.txt").write_text("new", encoding="utf-8")

    assert not (target / "old.txt").exists()
    assert (target / "new.txt").read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".archive.*-*"))


def test_staged_directory_preserves_live_tree_when_build_fails(tmp_path: Path):
    target = tmp_path / "archive"
    target.mkdir()
    (target / "old.txt").write_text("still live", encoding="utf-8")

    with pytest.raises(RuntimeError, match="render failed"):
        with staged_directory(target) as staging:
            (staging / "partial.txt").write_text("partial", encoding="utf-8")
            raise RuntimeError("render failed")

    assert (target / "old.txt").read_text(encoding="utf-8") == "still live"
    assert not (target / "partial.txt").exists()
    assert not list(tmp_path.glob(".archive.*-*"))


def test_final_deployed_size_report_includes_itself(tmp_path: Path):
    archive = tmp_path / "archive"
    edition = archive / "daily" / "2026-08-18"
    edition.mkdir(parents=True)
    (edition / "index.html").write_bytes(b"x" * 200)
    (archive / "index.html").write_text("archive", encoding="utf-8")

    report_path = enforce_published_archive_limits(archive)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    actual = sum(path.stat().st_size for path in archive.rglob("*") if path.is_file())
    assert report["total_bytes"] == actual
    assert report["status"] == "within"
    assert report["editions"][0]["bytes"] == 200
    assert report["capacity"]["level"] == "normal"
    assert report["capacity"]["remaining_bytes"] > 0


def test_final_deployed_size_gate_rejects_oversized_edition(tmp_path: Path):
    archive = tmp_path / "archive"
    edition = archive / "daily" / "2026-08-18"
    edition.mkdir(parents=True)
    (edition / "index.html").write_bytes(b"x" * 201)
    limits = PublishedArchiveLimits(
        total_bytes=10_000,
        shared_bytes=10_000,
        daily_bytes=200,
        period_bytes=10_000,
        weekly_bytes=10_000,
    )

    with pytest.raises(PublishedArchiveBudgetError, match="daily/2026-08-18"):
        enforce_published_archive_limits(archive, limits)

    report = json.loads(
        (archive / "data" / "published-size-report.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["status"] == "exceeded"


def test_capacity_forecast_warns_before_the_hard_gate(tmp_path: Path):
    archive = tmp_path / "archive"
    for day in ("2026-08-17", "2026-08-18"):
        edition = archive / "daily" / day
        edition.mkdir(parents=True)
        (edition / "index.html").write_bytes(b"x" * 6_000)
    limits = PublishedArchiveLimits(
        total_bytes=20_000,
        shared_bytes=10_000,
        daily_bytes=10_000,
        period_bytes=10_000,
        weekly_bytes=10_000,
    )

    with pytest.warns(PublishedArchiveCapacityWarning):
        report_path = enforce_published_archive_limits(archive, limits)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    capacity = report["capacity"]
    daily = capacity["forecast"]["collections"][0]
    assert report["status"] == "within"
    assert capacity["level"] in {"watch", "warning", "critical"}
    assert capacity["used_ratio"] >= 0.6
    assert capacity["forecast"]["estimated_monthly_growth_bytes"] > 0
    assert capacity["forecast"]["estimated_months_remaining"] is not None
    assert daily["observed_cadence_days"] == 1.0
    assert daily["estimated_editions_per_month"] == 30.44


def test_growth_forecast_can_warn_while_current_usage_is_low(tmp_path: Path):
    archive = tmp_path / "archive"
    for day in ("2026-08-17", "2026-08-18"):
        edition = archive / "daily" / day
        edition.mkdir(parents=True)
        (edition / "index.html").write_bytes(b"x" * 6_000)
    limits = PublishedArchiveLimits(
        total_bytes=100_000,
        shared_bytes=10_000,
        daily_bytes=10_000,
        period_bytes=10_000,
        weekly_bytes=10_000,
    )

    with pytest.warns(PublishedArchiveCapacityWarning):
        report_path = enforce_published_archive_limits(archive, limits)

    capacity = json.loads(report_path.read_text(encoding="utf-8"))["capacity"]
    assert capacity["signals"]["usage"] == "normal"
    assert capacity["signals"]["forecast"] in {"warning", "critical"}
    assert capacity["level"] in {"warning", "critical"}


def _daily_archive(root: Path, days: list[str], size: int) -> Path:
    archive = root / "archive"
    for day in days:
        edition = archive / "daily" / day
        edition.mkdir(parents=True)
        (edition / "index.html").write_bytes(b"x" * size)
    return archive


def test_retention_window_reports_a_bounded_steady_state(tmp_path: Path):
    """A sliding hot window does not approach the gate by accumulating.

    The unconditional countdown treated every archive as one that keeps all its
    editions online for ever, so it reported a deadline for an archive whose
    published size had in fact levelled off.
    """

    archive = _daily_archive(tmp_path, ["2026-10-15", "2026-10-16"], 6_000)
    limits = PublishedArchiveLimits(
        total_bytes=100_000_000,
        shared_bytes=10_000,
        daily_bytes=10_000,
        period_bytes=10_000,
        weekly_bytes=10_000,
    )

    report_path = enforce_published_archive_limits(
        archive,
        limits,
        retention_before="2026-09-01",
        retained_months=2,
    )

    capacity = json.loads(report_path.read_text(encoding="utf-8"))["capacity"]
    retention = capacity["forecast"]["retention"]
    assert retention["bounded"] is True
    assert retention["cutoff_exclusive"] == "2026-09-01"
    assert retention["retained_months"] == 2
    assert retention["beyond_window_bytes"] == 0
    # Two months of the observed monthly growth, plus the shared base.
    assert retention["projected_steady_state_bytes"] == (
        capacity["forecast"]["estimated_monthly_growth_bytes"] * 2
        + json.loads(report_path.read_text(encoding="utf-8"))["shared"]["bytes"]
    )
    assert capacity["forecast"]["estimated_months_remaining"] is None
    assert capacity["signals"]["forecast"] == "normal"


def test_steady_state_above_the_gate_still_raises_the_capacity_signal(tmp_path: Path):
    archive = _daily_archive(tmp_path, ["2026-10-15", "2026-10-16"], 6_000)
    limits = PublishedArchiveLimits(
        total_bytes=200_000,
        shared_bytes=10_000,
        daily_bytes=10_000,
        period_bytes=10_000,
        weekly_bytes=10_000,
    )

    with pytest.warns(PublishedArchiveCapacityWarning):
        report_path = enforce_published_archive_limits(
            archive,
            limits,
            retention_before="2026-09-01",
            retained_months=2,
        )

    capacity = json.loads(report_path.read_text(encoding="utf-8"))["capacity"]
    assert capacity["forecast"]["retention"]["bounded"] is False
    assert capacity["signals"]["forecast"] in {"warning", "critical", "exceeded"}
    # A window that does not fit is still a deadline, so the countdown stays.
    assert capacity["forecast"]["estimated_months_remaining"] is not None


def test_editions_retention_failed_to_release_are_measured_separately(tmp_path: Path):
    """An edition past the window that is not a cold stub defeats the steady state.

    Atlas deliberately keeps such an edition online when its cold package has no
    verification, so this is a real state, not a bug. The forecast has to carry
    its weight rather than average it into a growth rate.
    """

    archive = _daily_archive(
        tmp_path, ["2026-07-10", "2026-07-11", "2026-10-15", "2026-10-16"], 6_000
    )
    limits = PublishedArchiveLimits(
        total_bytes=100_000_000,
        shared_bytes=10_000,
        daily_bytes=10_000,
        period_bytes=10_000,
        weekly_bytes=10_000,
    )

    stale = enforce_published_archive_limits(
        archive,
        limits,
        retention_before="2026-09-01",
        retained_months=2,
    )
    stale_bytes = json.loads(stale.read_text(encoding="utf-8"))["capacity"]["forecast"][
        "retention"
    ]["beyond_window_bytes"]
    assert stale_bytes >= 12_000

    # Naming them as cold stubs removes them from the shortfall: that is
    # retention working, not retention failing.
    released = enforce_published_archive_limits(
        archive,
        limits,
        retention_before="2026-09-01",
        retained_months=2,
        cold_edition_ids={"2026-07-10", "2026-07-11"},
    )
    assert json.loads(released.read_text(encoding="utf-8"))["capacity"]["forecast"][
        "retention"
    ]["beyond_window_bytes"] == 0


def test_capacity_report_without_retention_keeps_the_countdown(tmp_path: Path):
    archive = _daily_archive(tmp_path, ["2026-08-17", "2026-08-18"], 6_000)
    limits = PublishedArchiveLimits(
        total_bytes=100_000,
        shared_bytes=10_000,
        daily_bytes=10_000,
        period_bytes=10_000,
        weekly_bytes=10_000,
    )

    with pytest.warns(PublishedArchiveCapacityWarning):
        report_path = enforce_published_archive_limits(archive, limits)

    capacity = json.loads(report_path.read_text(encoding="utf-8"))["capacity"]
    assert capacity["forecast"]["estimated_months_remaining"] is not None
    assert capacity["forecast"]["retention"]["cutoff_exclusive"] is None
    assert capacity["forecast"]["retention"]["bounded"] is False
