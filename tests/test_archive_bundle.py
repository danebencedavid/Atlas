from __future__ import annotations

import json
from pathlib import Path

from atlas.archive_bundle import CATALOG_SCHEMA
from atlas.archive_bundle import EDITION_SCHEMA
from atlas.archive_bundle import ImmutableEditionError
from atlas.archive_bundle import NARRATIVE_SCHEMA
from atlas.archive_bundle import archive_size_report
from atlas.archive_bundle import build_archive_catalog
from atlas.archive_bundle import ensure_edition_bundle
from atlas.archive_bundle import validate_edition_bundle


LOCATION = {
    "location_name": "Debrecen",
    "timezone_name": "Europe/Budapest",
    "latitude": 47.5316,
    "longitude": 21.6273,
}


def _period(root: Path, slug: str = "2026-08-16_2026-08-18") -> Path:
    edition = root / "periods" / slug
    (edition / "analysis").mkdir(parents=True)
    (edition / "assets" / "satellite_media").mkdir(parents=True)
    (edition / "data").mkdir()
    (edition / "index.html").write_text(
        "<html><head><title>Public edition</title></head><body>"
        "<nav>Navigation</nav><main><h1>Observed weather</h1>"
        "<p>Warm and dry.</p><script>secretScript()</script></main></body></html>",
        encoding="utf-8",
    )
    (edition / "analysis" / "index.html").write_text(
        "<html><head><title>Analysis edition</title></head>"
        "<body><main><h1>Three-day analysis</h1><p>A front passed.</p>"
        "<iframe src='../assets/plot.html'>fallback noise</iframe></main></body></html>",
        encoding="utf-8",
    )
    (edition / "assets" / "plot.html").write_text("rendered plot", encoding="utf-8")
    (edition / "assets" / "satellite_media" / "frame.webp").write_bytes(b"RIFFframe")
    (edition / "data" / "current_hourly.csv").write_text(
        "time,temperature_2m\n2026-08-18T00:00:00Z,21.4\n",
        encoding="utf-8",
    )
    return edition


def test_edition_bundle_is_deterministic_and_valid(tmp_path: Path):
    edition = _period(tmp_path)

    manifest_path = ensure_edition_bundle(edition, "periods", **LOCATION)
    first_manifest = manifest_path.read_bytes()
    first_narrative = (edition / "narrative.json").read_bytes()
    ensure_edition_bundle(edition, "periods", **LOCATION)

    assert manifest_path.read_bytes() == first_manifest
    assert (edition / "narrative.json").read_bytes() == first_narrative

    manifest = json.loads(first_manifest)
    narrative = json.loads(first_narrative)
    assert manifest["schema"] == EDITION_SCHEMA
    assert manifest["id"] == edition.name
    assert manifest["kind"] == "period"
    assert manifest["window"]["timezone"] == "Europe/Budapest"
    assert manifest["renderer"] == "atlas-archive/v1"
    assert manifest["immutability"]["frozen"] is True
    assert manifest["evidence"]["status"] == "self-contained"
    assert manifest["budget"]["status"] == "within"
    assert [resource["path"] for resource in manifest["datasets"]] == [
        "data/current_hourly.csv"
    ]
    assert manifest["media"][0]["retention"] == "legacy-hot"
    assert narrative["schema"] == NARRATIVE_SCHEMA
    pages = {page["path"]: page for page in narrative["pages"]}
    assert "Warm and dry." in pages["index.html"]["visible_text"]
    assert "Navigation" not in pages["index.html"]["visible_text"]
    assert "secretScript" not in pages["index.html"]["visible_text"]
    assert "fallback noise" not in pages["analysis/index.html"]["visible_text"]

    validation = validate_edition_bundle(edition)
    assert validation.valid, validation.errors
    assert validation.core_bytes <= validation.budget_bytes


def test_bundle_validation_detects_changed_evidence(tmp_path: Path):
    edition = _period(tmp_path)
    ensure_edition_bundle(edition, "periods", **LOCATION)

    (edition / "data" / "current_hourly.csv").write_text(
        "time,temperature_2m\n2026-08-18T00:00:00Z,99.0\n",
        encoding="utf-8",
    )

    validation = validate_edition_bundle(edition)
    assert not validation.valid
    assert any("Checksum mismatch" in error for error in validation.errors)
    assert any("content digest" in error for error in validation.errors)


def test_frozen_edition_requires_explicit_migration(tmp_path: Path):
    edition = _period(tmp_path)
    first_path = ensure_edition_bundle(edition, "periods", **LOCATION)
    first = json.loads(first_path.read_text(encoding="utf-8"))
    (edition / "index.html").write_text(
        "<html><body><main>Corrected edition</main></body></html>",
        encoding="utf-8",
    )

    try:
        ensure_edition_bundle(edition, "periods", **LOCATION)
    except ImmutableEditionError:
        pass
    else:
        raise AssertionError("A changed frozen edition was silently regenerated")

    ensure_edition_bundle(edition, "periods", migrate=True, **LOCATION)
    migrated = json.loads(first_path.read_text(encoding="utf-8"))
    assert (
        migrated["immutability"]["source_tree_sha256"]
        != first["immutability"]["source_tree_sha256"]
    )
    assert validate_edition_bundle(edition).valid


def test_large_text_dataset_gets_a_deterministic_compact_resource(tmp_path: Path):
    edition = _period(tmp_path)
    source = edition / "data" / "lightning_events.csv"
    source.write_text(
        "time,latitude,longitude\n" + "2026-08-18T00:00:00Z,47.5,21.6\n" * 5000,
        encoding="utf-8",
    )

    manifest_path = ensure_edition_bundle(edition, "periods", **LOCATION)
    first_compact = edition / "bundle" / "data" / "lightning_events.csv.gz"
    first_bytes = first_compact.read_bytes()
    ensure_edition_bundle(edition, "periods", **LOCATION)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lightning = next(
        resource
        for resource in manifest["datasets"]
        if resource.get("source_path") == "data/lightning_events.csv"
    )
    assert lightning["path"] == "bundle/data/lightning_events.csv.gz"
    assert lightning["compression"] == "gzip"
    assert lightning["bytes"] < lightning["source_bytes"]
    assert first_compact.read_bytes() == first_bytes
    assert manifest["legacy"]["cold_candidates"][0]["retention"] == "cold-candidate"
    assert validate_edition_bundle(edition).valid


def test_catalog_and_size_report_are_machine_readable(tmp_path: Path):
    edition = _period(tmp_path)
    ensure_edition_bundle(edition, "periods", **LOCATION)
    saved = {"daily": [], "periods": [edition], "weeks": []}

    catalog = build_archive_catalog(saved)
    sizes = archive_size_report(saved)

    assert catalog["schema"] == CATALOG_SCHEMA
    assert catalog["entries"][0]["href"].endswith("/analysis/index.html")
    assert catalog["entries"][0]["manifest_href"].endswith("/manifest.json")
    assert sizes["totals"]["editions"] == 1
    assert sizes["totals"]["over_budget"] == 0
    assert sizes["totals"]["legacy_source_bytes"] > 0
    assert sizes["totals"]["core_bytes"] > 0


def test_daily_bundle_reports_an_exceeded_core_budget(tmp_path: Path):
    edition = tmp_path / "daily" / "2026-08-18"
    (edition / "data").mkdir(parents=True)
    (edition / "index.html").write_text(
        "<html><body><main>Daily report</main></body></html>",
        encoding="utf-8",
    )
    (edition / "data" / "oversized.bin").write_bytes(b"x" * (300 * 1024))

    ensure_edition_bundle(edition, "daily", **LOCATION)

    validation = validate_edition_bundle(edition)
    assert not validation.valid
    assert any("budget exceeded" in error for error in validation.errors)
