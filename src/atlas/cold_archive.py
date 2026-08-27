from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests

from atlas.archive_bundle import validate_edition_bundle


COLD_PACKAGE_SCHEMA = "atlas.cold-package/1"
COLD_VERIFICATION_SCHEMA = "atlas.cold-release-verification/1"
GITHUB_API_VERSION = "2026-03-10"
MONTH_PATTERN = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
MAX_RELEASE_ASSET_BYTES = 2_000_000_000


class ColdArchiveError(ValueError):
    """Raised when a cold package or remote verification is unsafe."""


class ColdReleaseVerificationError(ColdArchiveError):
    """Raised when an edition has no matching verified cold copy."""


@dataclass(frozen=True)
class ColdPackage:
    month: str
    asset_path: Path
    metadata_path: Path
    bytes: int
    sha256: str
    editions: tuple[dict[str, str], ...]


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_month(month: str) -> None:
    if MONTH_PATTERN.fullmatch(month) is None:
        raise ColdArchiveError(f"Invalid archive month: {month!r}")


def _month_editions(reports_dir: Path, month: str) -> list[tuple[str, Path, dict[str, Any]]]:
    selected: list[tuple[str, Path, dict[str, Any]]] = []
    for collection in ("daily", "periods", "weeks"):
        parent = reports_dir / collection
        if not parent.is_dir():
            continue
        for edition in sorted(path for path in parent.iterdir() if path.is_dir()):
            manifest_path = edition / "manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not str(manifest.get("window", {}).get("end", "")).startswith(
                f"{month}-"
            ):
                continue
            validation = validate_edition_bundle(edition)
            if not validation.valid:
                raise ColdArchiveError(
                    f"Cannot package invalid edition {collection}/{edition.name}: "
                    + "; ".join(validation.errors)
                )
            selected.append((collection, edition, manifest))
    if not selected:
        raise ColdArchiveError(f"No frozen Atlas editions end in {month}")
    return selected


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_cold_package(
    reports_dir: Path,
    month: str,
    output_dir: Path,
) -> ColdPackage:
    """Create a deterministic monthly ZIP from validated immutable editions."""

    _validate_month(month)
    editions = _month_editions(reports_dir, month)
    files: list[tuple[str, Path, int, str]] = []
    edition_records: list[dict[str, str]] = []
    for collection, edition, manifest in editions:
        edition_records.append(
            {
                "collection": collection,
                "id": edition.name,
                "content_sha256": manifest["integrity"]["content_sha256"],
                "source_tree_sha256": manifest["immutability"]["source_tree_sha256"],
            }
        )
        for path in sorted(
            (item for item in edition.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(edition).as_posix(),
        ):
            archive_name = (
                Path("reports") / collection / edition.name / path.relative_to(edition)
            ).as_posix()
            files.append((archive_name, path, path.stat().st_size, _sha256(path)))

    embedded_manifest = {
        "schema": COLD_PACKAGE_SCHEMA,
        "month": month,
        "editions": edition_records,
        "files": [
            {"path": name, "bytes": size, "sha256": digest}
            for name, _, size, digest in files
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    asset = output_dir / f"atlas-debrecen-archive-{month}.zip"
    temporary = output_dir / f".{asset.name}.staging-{uuid.uuid4().hex}"
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            archive.writestr(_zip_info("atlas-cold-manifest.json"), _json_bytes(embedded_manifest))
            for archive_name, source, size, digest in files:
                content = source.read_bytes()
                if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                    raise ColdArchiveError(
                        f"Edition changed while packaging: {archive_name}"
                    )
                archive.writestr(_zip_info(archive_name), content)
        if temporary.stat().st_size > MAX_RELEASE_ASSET_BYTES:
            raise ColdArchiveError(
                f"Cold archive exceeds GitHub's release-asset safety limit: {temporary.stat().st_size} bytes"
            )
        temporary.replace(asset)
    finally:
        if temporary.exists():
            temporary.unlink()

    package_sha256 = _sha256(asset)
    metadata_path = asset.with_suffix(".metadata.json")
    metadata = {
        "schema": COLD_PACKAGE_SCHEMA,
        "month": month,
        "asset": asset.name,
        "bytes": asset.stat().st_size,
        "sha256": package_sha256,
        "editions": edition_records,
    }
    metadata_path.write_bytes(_json_bytes(metadata))
    return ColdPackage(
        month=month,
        asset_path=asset,
        metadata_path=metadata_path,
        bytes=asset.stat().st_size,
        sha256=package_sha256,
        editions=tuple(edition_records),
    )


def load_cold_package(asset_path: Path) -> ColdPackage:
    metadata_path = asset_path.with_suffix(".metadata.json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ColdArchiveError(f"Unreadable cold-package metadata: {metadata_path}") from exc
    if metadata.get("schema") != COLD_PACKAGE_SCHEMA:
        raise ColdArchiveError("Unsupported cold-package metadata schema")
    actual_bytes = asset_path.stat().st_size
    actual_sha256 = _sha256(asset_path)
    if metadata.get("bytes") != actual_bytes or metadata.get("sha256") != actual_sha256:
        raise ColdArchiveError("Cold package differs from its local metadata")
    with zipfile.ZipFile(asset_path) as archive:
        if archive.testzip() is not None:
            raise ColdArchiveError("Cold package contains a corrupt ZIP member")
        embedded = json.loads(archive.read("atlas-cold-manifest.json"))
        if embedded.get("schema") != COLD_PACKAGE_SCHEMA:
            raise ColdArchiveError("Cold package has an unsupported embedded manifest")
        for resource in embedded.get("files", []):
            content = archive.read(resource["path"])
            if len(content) != resource["bytes"]:
                raise ColdArchiveError(f"Cold ZIP size mismatch: {resource['path']}")
            if hashlib.sha256(content).hexdigest() != resource["sha256"]:
                raise ColdArchiveError(f"Cold ZIP checksum mismatch: {resource['path']}")
    if embedded.get("month") != metadata.get("month"):
        raise ColdArchiveError("Cold package month does not match its metadata")
    if embedded.get("editions") != metadata.get("editions"):
        raise ColdArchiveError("Cold package edition list does not match its metadata")
    return ColdPackage(
        month=metadata["month"],
        asset_path=asset_path,
        metadata_path=metadata_path,
        bytes=actual_bytes,
        sha256=actual_sha256,
        editions=tuple(metadata["editions"]),
    )


def _verify_asset_metadata(asset: dict[str, Any], package: ColdPackage) -> None:
    expected_digest = f"sha256:{package.sha256}"
    if asset.get("name") != package.asset_path.name:
        raise ColdArchiveError("GitHub release asset name does not match the package")
    if asset.get("state") != "uploaded":
        raise ColdArchiveError(
            f"GitHub release asset is not complete: {asset.get('state')!r}"
        )
    if asset.get("size") != package.bytes:
        raise ColdArchiveError("GitHub release asset size does not match the package")
    if asset.get("digest") != expected_digest:
        raise ColdArchiveError("GitHub release asset SHA-256 does not match the package")


def _headers(token: str, accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {
        "Accept": accept,
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "Atlas-cold-archive",
    }


def _response_json(response: requests.Response, operation: str) -> dict[str, Any]:
    if response.status_code >= 400:
        detail = response.text[:500]
        raise ColdArchiveError(
            f"GitHub {operation} failed with HTTP {response.status_code}: {detail}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ColdArchiveError(f"GitHub {operation} returned invalid JSON") from exc


def _release_for_year(
    session: requests.Session,
    api_url: str,
    repository: str,
    token: str,
    year: str,
) -> dict[str, Any]:
    tag = f"atlas-archive-{year}"
    release_url = f"{api_url.rstrip('/')}/repos/{repository}/releases/tags/{quote(tag)}"
    response = session.get(release_url, headers=_headers(token), timeout=(10, 60))
    if response.status_code != 404:
        return _response_json(response, "release lookup")
    create_url = f"{api_url.rstrip('/')}/repos/{repository}/releases"
    response = session.post(
        create_url,
        headers=_headers(token),
        json={
            "tag_name": tag,
            "name": f"Atlas cold archive {year}",
            "body": (
                "Immutable monthly Atlas weather-report bundles. Each asset is "
                "verified by byte count, GitHub SHA-256, and a complete download."
            ),
            "draft": False,
            "prerelease": False,
            "make_latest": "false",
        },
        timeout=(10, 60),
    )
    return _response_json(response, "release creation")


def _download_digest(
    session: requests.Session,
    asset: dict[str, Any],
    token: str,
) -> tuple[int, str]:
    response = session.get(
        asset["url"],
        headers=_headers(token, "application/octet-stream"),
        stream=True,
        allow_redirects=True,
        timeout=(10, 300),
    )
    if response.status_code >= 400:
        raise ColdArchiveError(
            f"GitHub release download failed with HTTP {response.status_code}"
        )
    digest = hashlib.sha256()
    size = 0
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if not chunk:
            continue
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _write_verification_record(
    reports_dir: Path,
    package: ColdPackage,
    repository: str,
    release: dict[str, Any],
    asset: dict[str, Any],
) -> Path:
    record_path = reports_dir / "cold" / f"{package.month}.json"
    stable = {
        "schema": COLD_VERIFICATION_SCHEMA,
        "status": "verified",
        "month": package.month,
        "repository": repository,
        "release_tag": release["tag_name"],
        "release_url": release["html_url"],
        "asset": package.asset_path.name,
        "asset_url": asset["browser_download_url"],
        "asset_id": asset["id"],
        "bytes": package.bytes,
        "sha256": package.sha256,
        "github_digest": asset["digest"],
        "verification": {
            "local_package": True,
            "github_metadata": True,
            "downloaded_copy": True,
        },
        "editions": list(package.editions),
    }
    if record_path.is_file():
        existing = json.loads(record_path.read_text(encoding="utf-8"))
        comparison = {key: existing.get(key) for key in stable}
        if comparison == stable:
            return record_path
    record = {
        **stable,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    record_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = record_path.with_name(f".{record_path.name}.staging-{uuid.uuid4().hex}")
    try:
        temporary.write_bytes(_json_bytes(record))
        temporary.replace(record_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return record_path


def upload_and_verify_cold_release(
    package: ColdPackage,
    reports_dir: Path,
    repository: str,
    token: str,
    *,
    api_url: str = "https://api.github.com",
    session: requests.Session | None = None,
) -> Path:
    """Upload idempotently, verify metadata and re-download, then record success."""

    if not repository or "/" not in repository:
        raise ColdArchiveError("GitHub repository must use OWNER/REPO form")
    if not token:
        raise ColdArchiveError("GITHUB_TOKEN is required for cold-release upload")
    package = load_cold_package(package.asset_path)
    session = session or requests.Session()
    release = _release_for_year(
        session,
        api_url,
        repository,
        token,
        package.month[:4],
    )
    matching = [
        item for item in release.get("assets", []) if item.get("name") == package.asset_path.name
    ]
    if matching:
        asset = matching[0]
        _verify_asset_metadata(asset, package)
    else:
        upload_url = str(release["upload_url"]).split("{", maxsplit=1)[0]
        with package.asset_path.open("rb") as stream:
            response = session.post(
                upload_url,
                params={"name": package.asset_path.name},
                headers={
                    **_headers(token),
                    "Content-Type": "application/zip",
                },
                data=stream,
                timeout=(10, 600),
            )
        asset = _response_json(response, "release-asset upload")
        for attempt in range(7):
            try:
                _verify_asset_metadata(asset, package)
                break
            except ColdArchiveError:
                if attempt == 6:
                    raise
                time.sleep(2)
                response = session.get(
                    asset["url"], headers=_headers(token), timeout=(10, 60)
                )
                asset = _response_json(response, "release-asset verification")

    downloaded_bytes, downloaded_sha256 = _download_digest(session, asset, token)
    if downloaded_bytes != package.bytes or downloaded_sha256 != package.sha256:
        raise ColdArchiveError(
            "Downloaded GitHub release asset does not match the local cold package"
        )
    return _write_verification_record(
        reports_dir,
        package,
        repository,
        release,
        asset,
    )


def require_verified_cold_release(
    reports_dir: Path,
    collection: str,
    edition_id: str,
) -> Path:
    """Safety gate for any future pruning implementation; this function never deletes."""

    edition = reports_dir / collection / edition_id
    manifest = json.loads((edition / "manifest.json").read_text(encoding="utf-8"))
    month = str(manifest["window"]["end"])[:7]
    record_path = reports_dir / "cold" / f"{month}.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ColdReleaseVerificationError(
            f"No verified cold release covers {collection}/{edition_id}"
        ) from exc
    if record.get("schema") != COLD_VERIFICATION_SCHEMA or record.get("status") != "verified":
        raise ColdReleaseVerificationError(f"Cold release {month} is not verified")
    expected = {
        "collection": collection,
        "id": edition_id,
        "content_sha256": manifest["integrity"]["content_sha256"],
        "source_tree_sha256": manifest["immutability"]["source_tree_sha256"],
    }
    if expected not in record.get("editions", []):
        raise ColdReleaseVerificationError(
            f"Verified cold release does not match {collection}/{edition_id}"
        )
    return record_path


def _package_from_args(args: argparse.Namespace) -> int:
    package = build_cold_package(args.reports_dir, args.month, args.output_dir)
    print(package.asset_path)
    print(f"sha256:{package.sha256}")
    return 0


def _upload_from_args(args: argparse.Namespace) -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = args.repository or os.environ.get("GITHUB_REPOSITORY", "")
    package = load_cold_package(args.asset)
    record = upload_and_verify_cold_release(
        package,
        args.reports_dir,
        repository,
        token,
        api_url=args.api_url or os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    print(record)
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Package and verify immutable Atlas monthly cold archives."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    package_parser = commands.add_parser("package")
    package_parser.add_argument("--month", required=True, help="Calendar month, YYYY-MM")
    package_parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    package_parser.add_argument("--output-dir", type=Path, default=Path("dist/cold"))
    package_parser.set_defaults(handler=_package_from_args)
    upload_parser = commands.add_parser("upload")
    upload_parser.add_argument("--asset", required=True, type=Path)
    upload_parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    upload_parser.add_argument("--repository")
    upload_parser.add_argument("--api-url")
    upload_parser.set_defaults(handler=_upload_from_args)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
