from __future__ import annotations

import json
import shutil
import statistics
import uuid
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
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


class PublishedArchiveCapacityWarning(UserWarning):
    """Warns that the archive is approaching, but has not crossed, its hard gate."""


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


def _edition_end_date(edition_id: str) -> date | None:
    try:
        return date.fromisoformat(edition_id[-10:])
    except ValueError:
        return None


def _growth_forecast(editions: list[dict[str, object]]) -> dict[str, object]:
    """Estimate growth from recent edition sizes and the archive's actual cadence."""

    collections: list[dict[str, object]] = []
    estimated_monthly_growth = 0
    for collection in ("daily", "periods", "weeks"):
        items = [item for item in editions if item["collection"] == collection]
        recent = items[-8:]
        average_bytes = (
            round(sum(int(item["bytes"]) for item in recent) / len(recent))
            if recent
            else 0
        )
        ends = sorted(
            {
                end
                for item in items
                if (end := _edition_end_date(str(item["id"]))) is not None
            }
        )
        gaps = [
            (right - left).days
            for left, right in zip(ends, ends[1:])
            if (right - left).days > 0
        ]
        cadence_days = round(float(statistics.median(gaps)), 2) if gaps else None
        editions_per_month = (
            round(30.4375 / cadence_days, 2) if cadence_days else 0.0
        )
        monthly_bytes = round(average_bytes * editions_per_month)
        estimated_monthly_growth += monthly_bytes
        collections.append(
            {
                "collection": collection,
                "recent_sample_count": len(recent),
                "average_edition_bytes": average_bytes,
                "observed_cadence_days": cadence_days,
                "estimated_editions_per_month": editions_per_month,
                "estimated_monthly_growth_bytes": monthly_bytes,
            }
        )
    return {
        "method": "recent-8-edition-mean-and-median-observed-cadence",
        "estimated_monthly_growth_bytes": estimated_monthly_growth,
        "collections": collections,
    }


def _capacity_level(used_ratio: float) -> str:
    if used_ratio > 1.0:
        return "exceeded"
    if used_ratio >= 0.9:
        return "critical"
    if used_ratio >= 0.75:
        return "warning"
    if used_ratio >= 0.6:
        return "watch"
    return "normal"


def _forecast_level(months_remaining: float | None) -> str:
    if months_remaining is None:
        return "normal"
    if months_remaining <= 1:
        return "critical"
    if months_remaining <= 2:
        return "warning"
    if months_remaining <= 3:
        return "watch"
    return "normal"


def _highest_capacity_level(*levels: str) -> str:
    order = {"normal": 0, "watch": 1, "warning": 2, "critical": 3, "exceeded": 4}
    return max(levels, key=order.__getitem__)


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
    forecast = _growth_forecast(editions)

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
        remaining_bytes = max(limits.total_bytes - total_bytes, 0)
        used_ratio = total_bytes / limits.total_bytes
        monthly_growth = int(forecast["estimated_monthly_growth_bytes"])
        estimated_months_remaining = (
            round(remaining_bytes / monthly_growth, 1)
            if monthly_growth > 0
            else None
        )
        usage_level = _capacity_level(used_ratio)
        forecast_level = _forecast_level(estimated_months_remaining)
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
            "capacity": {
                "level": _highest_capacity_level(usage_level, forecast_level),
                "signals": {
                    "usage": usage_level,
                    "forecast": forecast_level,
                },
                "used_ratio": round(used_ratio, 6),
                "used_percent": round(used_ratio * 100, 2),
                "remaining_bytes": remaining_bytes,
                "soft_thresholds": {
                    "watch_ratio": 0.6,
                    "warning_ratio": 0.75,
                    "critical_ratio": 0.9,
                },
                "forecast": {
                    **forecast,
                    "estimated_months_remaining": estimated_months_remaining,
                },
            },
            "editions": editions,
            "violations": violations,
        }

    # A rounded percentage or forecast can make the self-reported length oscillate
    # by a byte or two. Choose the first size that can contain its own payload and
    # use harmless trailing JSON whitespace when an exact fixed point does not exist.
    report_bytes = 0
    for _ in range(24):
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
        if len(document) <= report_bytes:
            padding = report_bytes - len(document)
            if padding:
                document = document[:-1] + (b" " * padding) + b"\n"
            break
        report_bytes = len(document)
    else:
        raise RuntimeError("Published size report did not converge to a bounded size")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(document)
    if report_path.stat().st_size != report_bytes:
        raise RuntimeError("Published size report did not converge to its final size")
    if final_payload["violations"]:
        raise PublishedArchiveBudgetError(
            "Published archive size gate failed: "
            + ", ".join(str(item) for item in final_payload["violations"])
        )
    capacity = final_payload["capacity"]
    if capacity["level"] != "normal":
        warnings.warn(
            "Published archive capacity is "
            f"{capacity['level']} at {capacity['used_percent']}% of the hard limit; "
            f"the current cadence estimates {capacity['forecast']['estimated_months_remaining']} "
            "months remaining. Review retention before adding more hot history.",
            PublishedArchiveCapacityWarning,
            stacklevel=2,
        )
    return report_path
