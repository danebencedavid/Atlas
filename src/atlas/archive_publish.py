from __future__ import annotations

import json
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


PUBLISHED_SIZE_SCHEMA = "atlas.published-archive-size/1"


@dataclass(frozen=True)
class PublishedArchiveLimits:
    total_bytes: int = 256 * 1024 * 1024
    shared_bytes: int = 16 * 1024 * 1024
    daily_bytes: int = 1 * 1024 * 1024
    period_bytes: int = 16 * 1024 * 1024
    weekly_bytes: int = 8 * 1024 * 1024

    def edition_limit(self, collection: str) -> int:
        return {
            "daily": self.daily_bytes,
            "periods": self.period_bytes,
            "weeks": self.weekly_bytes,
        }[collection]


class PublishedArchiveBudgetError(ValueError):
    """Raised before deployment when a completed archive exceeds a hard limit."""


def _remove_staging_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


@contextmanager
def staged_directory(target: Path) -> Iterator[Path]:
    """Build beside a live directory, then swap it in with rollback protection."""

    target = target.resolve()
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staging = parent / f".{target.name}.staging-{token}"
    backup = parent / f".{target.name}.backup-{token}"
    staging.mkdir()
    try:
        yield staging
    except BaseException:
        _remove_staging_tree(staging)
        raise

    moved_live = False
    try:
        if target.exists():
            target.rename(backup)
            moved_live = True
        staging.rename(target)
    except BaseException:
        if moved_live and backup.exists() and not target.exists():
            backup.rename(target)
        _remove_staging_tree(staging)
        raise
    if backup.exists():
        _remove_staging_tree(backup)


def _tree_bytes(root: Path, *, exclude: Path | None = None) -> int:
    return sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file() and path != exclude
    )


def enforce_published_archive_limits(
    archive_dir: Path,
    limits: PublishedArchiveLimits | None = None,
) -> Path:
    """Measure the final deployed tree, write its report, and enforce hard gates."""

    limits = limits or PublishedArchiveLimits()
    report_path = archive_dir / "data" / "published-size-report.v1.json"
    editions: list[dict[str, object]] = []
    edition_total = 0
    for collection in ("daily", "periods", "weeks"):
        parent = archive_dir / collection
        limit = limits.edition_limit(collection)
        if not parent.is_dir():
            continue
        for edition in sorted(path for path in parent.iterdir() if path.is_dir()):
            size = _tree_bytes(edition)
            edition_total += size
            editions.append(
                {
                    "collection": collection,
                    "id": edition.name,
                    "bytes": size,
                    "limit_bytes": limit,
                    "status": "within" if size <= limit else "exceeded",
                }
            )

    base_total = _tree_bytes(archive_dir, exclude=report_path)
    base_shared = base_total - edition_total

    def payload(report_bytes: int) -> dict[str, object]:
        total_bytes = base_total + report_bytes
        shared_bytes = base_shared + report_bytes
        violations = [
            f"{item['collection']}/{item['id']}"
            for item in editions
            if item["status"] == "exceeded"
        ]
        if shared_bytes > limits.shared_bytes:
            violations.append("shared")
        if total_bytes > limits.total_bytes:
            violations.append("total")
        return {
            "schema": PUBLISHED_SIZE_SCHEMA,
            "status": "within" if not violations else "exceeded",
            "total_bytes": total_bytes,
            "limits": {
                "total_bytes": limits.total_bytes,
                "shared_bytes": limits.shared_bytes,
                "daily_bytes": limits.daily_bytes,
                "period_bytes": limits.period_bytes,
                "weekly_bytes": limits.weekly_bytes,
            },
            "shared": {
                "bytes": shared_bytes,
                "limit_bytes": limits.shared_bytes,
                "status": (
                    "within" if shared_bytes <= limits.shared_bytes else "exceeded"
                ),
            },
            "editions": editions,
            "violations": violations,
        }

    report_bytes = 0
    for _ in range(12):
        document = (
            json.dumps(
                payload(report_bytes),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        if len(document) == report_bytes:
            break
        report_bytes = len(document)
    final_payload = payload(report_bytes)
    document = (
        json.dumps(
            final_payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(document)
    if report_path.stat().st_size != report_bytes:
        raise RuntimeError("Published size report did not converge to its final size")
    if final_payload["violations"]:
        raise PublishedArchiveBudgetError(
            "Published archive size gate failed: "
            + ", ".join(str(item) for item in final_payload["violations"])
        )
    return report_path
