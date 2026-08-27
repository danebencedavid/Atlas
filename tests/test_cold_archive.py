from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from atlas.archive_bundle import ensure_edition_bundle
from atlas.cold_archive import build_cold_package
from atlas.cold_archive import ColdArchiveError
from atlas.cold_archive import ColdReleaseVerificationError
from atlas.cold_archive import load_cold_package
from atlas.cold_archive import require_verified_cold_release
from atlas.cold_archive import _write_verification_record
from atlas.cold_archive import upload_and_verify_cold_release


LOCATION = {
    "location_name": "Debrecen",
    "timezone_name": "Europe/Budapest",
    "latitude": 47.5316,
    "longitude": 21.6273,
}


def _edition(reports: Path, day: str = "2026-08-18") -> Path:
    edition = reports / "daily" / day
    (edition / "data").mkdir(parents=True)
    (edition / "index.html").write_text(
        "<html><body><main>Daily evidence</main></body></html>",
        encoding="utf-8",
    )
    (edition / "data" / "daily.csv").write_text(
        "time,temperature\n00:00,20\n", encoding="utf-8"
    )
    ensure_edition_bundle(edition, "daily", **LOCATION)
    return edition


def test_cold_package_is_deterministic_and_self_verifying(tmp_path: Path):
    reports = tmp_path / "reports"
    edition = _edition(reports)
    first = build_cold_package(reports, "2026-08", tmp_path / "dist")
    first_bytes = first.asset_path.read_bytes()

    second = build_cold_package(reports, "2026-08", tmp_path / "dist")
    loaded = load_cold_package(second.asset_path)

    assert second.asset_path.read_bytes() == first_bytes
    assert loaded.sha256 == first.sha256
    assert loaded.editions[0]["id"] == edition.name
    with zipfile.ZipFile(second.asset_path) as archive:
        embedded = json.loads(archive.read("atlas-cold-manifest.json"))
        assert embedded["month"] == "2026-08"
        assert "reports/daily/2026-08-18/index.html" in {
            resource["path"] for resource in embedded["files"]
        }


def test_cold_package_refuses_invalid_or_empty_month(tmp_path: Path):
    reports = tmp_path / "reports"
    edition = _edition(reports)
    (edition / "index.html").write_text("changed", encoding="utf-8")

    with pytest.raises(ColdArchiveError, match="invalid edition"):
        build_cold_package(reports, "2026-08", tmp_path / "dist")
    with pytest.raises(ColdArchiveError, match="No frozen"):
        build_cold_package(reports, "2026-07", tmp_path / "dist")


def test_pruning_guard_requires_exact_verified_release(tmp_path: Path):
    reports = tmp_path / "reports"
    edition = _edition(reports)
    package = build_cold_package(reports, "2026-08", tmp_path / "dist")

    with pytest.raises(ColdReleaseVerificationError, match="No verified"):
        require_verified_cold_release(reports, "daily", edition.name)

    asset = {
        "id": 42,
        "name": package.asset_path.name,
        "state": "uploaded",
        "size": package.bytes,
        "digest": f"sha256:{package.sha256}",
        "url": "https://api.github.test/assets/42",
        "browser_download_url": "https://github.test/releases/archive.zip",
    }
    release = {
        "tag_name": "atlas-archive-2026",
        "html_url": "https://github.test/releases/atlas-archive-2026",
    }
    record = _write_verification_record(
        reports, package, "owner/repo", release, asset
    )

    assert require_verified_cold_release(reports, "daily", edition.name) == record
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["editions"][0]["source_tree_sha256"] = "0" * 64
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ColdReleaseVerificationError, match="does not match"):
        require_verified_cold_release(reports, "daily", edition.name)


def test_existing_remote_asset_must_match_exact_package(tmp_path: Path):
    reports = tmp_path / "reports"
    _edition(reports)
    package = build_cold_package(reports, "2026-08", tmp_path / "dist")
    mismatched = {
        "name": package.asset_path.name,
        "state": "uploaded",
        "size": package.bytes,
        "digest": "sha256:" + "0" * 64,
    }

    from atlas.cold_archive import _verify_asset_metadata

    with pytest.raises(ColdArchiveError, match="SHA-256"):
        _verify_asset_metadata(mismatched, package)


class _FakeResponse:
    def __init__(self, payload=None, content: bytes = b"", status_code: int = 200):
        self._payload = payload
        self._content = content
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self._content), chunk_size):
            yield self._content[start : start + chunk_size]


class _FakeSession:
    def __init__(self, release: dict, download: bytes):
        self.release = release
        self.download = download
        self.posts = 0

    def get(self, url: str, **kwargs):
        del kwargs
        if "/releases/tags/" in url:
            return _FakeResponse(self.release)
        return _FakeResponse(content=self.download)

    def post(self, *args, **kwargs):
        del args, kwargs
        self.posts += 1
        raise AssertionError("An already verified asset must not be uploaded again")


def test_remote_round_trip_is_required_before_verification_record(tmp_path: Path):
    reports = tmp_path / "reports"
    _edition(reports)
    package = build_cold_package(reports, "2026-08", tmp_path / "dist")
    asset = {
        "id": 42,
        "name": package.asset_path.name,
        "state": "uploaded",
        "size": package.bytes,
        "digest": f"sha256:{package.sha256}",
        "url": "https://api.github.test/assets/42",
        "browser_download_url": "https://github.test/releases/archive.zip",
    }
    release = {
        "tag_name": "atlas-archive-2026",
        "html_url": "https://github.test/releases/atlas-archive-2026",
        "assets": [asset],
    }
    mismatched = _FakeSession(release, b"not the archive")

    with pytest.raises(ColdArchiveError, match="Downloaded"):
        upload_and_verify_cold_release(
            package,
            reports,
            "owner/repo",
            "token",
            api_url="https://api.github.test",
            session=mismatched,
        )
    assert not (reports / "cold" / "2026-08.json").exists()

    matching = _FakeSession(release, package.asset_path.read_bytes())
    record = upload_and_verify_cold_release(
        package,
        reports,
        "owner/repo",
        "token",
        api_url="https://api.github.test",
        session=matching,
    )
    assert record.is_file()
    assert json.loads(record.read_text(encoding="utf-8"))["verification"] == {
        "local_package": True,
        "github_metadata": True,
        "downloaded_copy": True,
    }
