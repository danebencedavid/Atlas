from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.archive_publish import enforce_published_archive_limits
from atlas.archive_publish import PublishedArchiveBudgetError
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
