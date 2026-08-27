from __future__ import annotations

import gzip
import hashlib
import io
import json
import mimetypes
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from atlas.archive_figures import compact_edition_figures


EDITION_SCHEMA = "atlas.edition/2"
NARRATIVE_SCHEMA = "atlas.narrative/1"
CATALOG_SCHEMA = "atlas.archive-catalog/1"
RENDERER_VERSION = "atlas-archive/v1"
BUNDLE_GENERATOR_VERSION = "atlas.archive-bundle/4"

CORE_SIZE_BUDGETS = {
    "daily": 256 * 1024,
    "period": 2 * 1024 * 1024,
    "weekly": 2 * 1024 * 1024,
}

COLLECTION_KINDS = {
    "daily": "daily",
    "periods": "period",
    "weeks": "weekly",
}

MEDIA_SUFFIXES = {".avif", ".jpeg", ".jpg", ".mp4", ".png", ".webm", ".webp"}
GENERATED_BUNDLE_FILES = {"manifest.json", "narrative.json"}
COMPACT_TEXT_THRESHOLD_BYTES = 128 * 1024
COMPACT_TEXT_SUFFIXES = {".csv", ".json"}
INTEGRITY_TEXT_SUFFIXES = {".csv", ".html", ".json"}


@dataclass(frozen=True)
class BundleValidation:
    errors: tuple[str, ...]
    core_bytes: int
    budget_bytes: int

    @property
    def valid(self) -> bool:
        return not self.errors


class ImmutableEditionError(ValueError):
    """Raised when a frozen edition changed without an explicit migration."""


class _NarrativeParser(HTMLParser):
    """Capture a compact, stable snapshot of the visible publication wording."""

    _ignored = {"script", "style", "noscript", "svg", "iframe", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._main_depth = 0
        self._body_depth = 0
        self._title_depth = 0
        self._title_parts: list[str] = []
        self._main_parts: list[str] = []
        self._body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.casefold()
        if tag in self._ignored:
            self._ignored_depth += 1
        if tag == "main":
            self._main_depth += 1
        elif tag == "body":
            self._body_depth += 1
        elif tag == "title":
            self._title_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "main" and self._main_depth:
            self._main_depth -= 1
        elif tag == "body" and self._body_depth:
            self._body_depth -= 1
        elif tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag in self._ignored and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._title_depth:
            self._title_parts.append(text)
        if self._main_depth:
            self._main_parts.append(text)
        elif self._body_depth:
            self._body_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self._title_parts).strip()

    @property
    def visible_text(self) -> str:
        parts = self._main_parts or self._body_parts
        return " ".join(parts).strip()


def _integrity_bytes(path: Path) -> bytes:
    """Return bytes as Git deploys tracked text, independent of checkout OS."""

    content = path.read_bytes()
    if path.suffix.casefold() in INTEGRITY_TEXT_SUFFIXES:
        return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return content


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


def _write_if_changed(path: Path, payload: dict[str, Any]) -> bytes:
    content = _json_bytes(payload)
    if not path.is_file() or path.read_bytes() != content:
        path.write_bytes(content)
    return content


def _write_bytes_if_changed(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_bytes() != content:
        path.write_bytes(content)


def _edition_window(slug: str, collection: str) -> tuple[str, str, str]:
    try:
        kind = COLLECTION_KINDS[collection]
    except KeyError as exc:
        raise ValueError(f"Unsupported archive collection: {collection}") from exc

    if collection == "daily":
        date.fromisoformat(slug)
        return kind, slug, slug

    try:
        start, end = slug.split("_", maxsplit=1)
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError(f"Invalid {collection} edition slug: {slug}") from exc
    if end_date < start_date:
        raise ValueError(f"Edition ends before it starts: {slug}")
    return kind, start, end


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix.casefold() == ".npz":
        return "application/x-numpy-archive"
    return "application/octet-stream"


def _resource(path: Path, root: Path) -> dict[str, Any]:
    content = _integrity_bytes(path)
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "media_type": _media_type(path),
    }


def _page_snapshot(path: Path, root: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    parser = _NarrativeParser()
    parser.feed(source)
    parser.close()
    return {
        "path": path.relative_to(root).as_posix(),
        "title": parser.title or path.stem.replace("-", " ").title(),
        "visible_text": parser.visible_text,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }


def _source_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.name not in GENERATED_BUNDLE_FILES
            and path.relative_to(root).parts[0] != "bundle"
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _source_tree_digest(paths: Iterable[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix()
        content = _integrity_bytes(path)
        digest.update(
            f"{relative}\0{len(content)}\0{hashlib.sha256(content).hexdigest()}\n".encode(
                "utf-8"
            )
        )
    return digest.hexdigest()


def _gzip_bytes(content: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        compresslevel=9,
        fileobj=output,
        mtime=0,
    ) as stream:
        stream.write(content)
    return output.getvalue()


def _dataset_resource(path: Path, root: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    source = _resource(path, root)
    if (
        path.suffix.casefold() not in COMPACT_TEXT_SUFFIXES
        or source["bytes"] < COMPACT_TEXT_THRESHOLD_BYTES
    ):
        return {**source, "retention": "core"}, None

    relative = path.relative_to(root)
    compact_path = root / "bundle" / relative.parent / f"{relative.name}.gz"
    _write_bytes_if_changed(compact_path, _gzip_bytes(_integrity_bytes(path)))
    compact = _resource(compact_path, root)
    return (
        {
            **compact,
            "retention": "core",
            "compression": "gzip",
            "source_path": source["path"],
            "source_bytes": source["bytes"],
            "source_sha256": source["sha256"],
            "source_media_type": source["media_type"],
        },
        {**source, "retention": "cold-candidate"},
    )


def _content_digest(resources: Iterable[dict[str, Any]], narrative_sha256: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"narrative.json\0{narrative_sha256}\n".encode("utf-8"))
    for resource in resources:
        digest.update(
            f"{resource['path']}\0{resource['bytes']}\0{resource['sha256']}\n".encode(
                "utf-8"
            )
        )
    return digest.hexdigest()


def ensure_edition_bundle(
    edition_dir: Path,
    collection: str,
    *,
    location_name: str,
    timezone_name: str,
    latitude: float,
    longitude: float,
    migrate: bool = False,
) -> Path:
    """Write deterministic bundle metadata beside a preserved legacy edition.

    The first archive migration is deliberately additive: legacy pages and assets
    remain untouched, while data, narrative and retention metadata gain a stable
    contract for the shared archive renderer planned for the next phase.
    """

    if not edition_dir.is_dir():
        raise FileNotFoundError(edition_dir)
    if not (edition_dir / "index.html").is_file():
        raise ValueError(f"Edition has no index.html: {edition_dir}")

    slug = edition_dir.name
    kind, start, end = _edition_window(slug, collection)
    source_files = _source_files(edition_dir)
    source_tree_sha256 = _source_tree_digest(source_files, edition_dir)
    manifest_path = edition_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            if not migrate:
                raise ImmutableEditionError(
                    f"Edition {slug} has an unreadable manifest; use explicit migration"
                ) from exc
        else:
            immutable = existing.get("immutability", {})
            unchanged = (
                existing.get("schema") == EDITION_SCHEMA
                and existing.get("generator") == BUNDLE_GENERATOR_VERSION
                and immutable.get("frozen") is True
                and immutable.get("source_tree_sha256") == source_tree_sha256
                and immutable.get("source_file_count") == len(source_files)
            )
            if unchanged:
                return manifest_path
            if not migrate:
                raise ImmutableEditionError(
                    f"Frozen edition {slug} changed or requires a schema migration; "
                    "rerun through the explicit archive migration path"
                )
    pages = [
        path
        for path in source_files
        if path.suffix.casefold() == ".html"
        and "assets" not in path.relative_to(edition_dir).parts
    ]
    data_files = [
        path
        for path in source_files
        if path.relative_to(edition_dir).parts[0] == "data"
    ]
    media_files = [
        path
        for path in source_files
        if path.suffix.casefold() in MEDIA_SUFFIXES
        and path.relative_to(edition_dir).parts[0] == "assets"
    ]
    legacy_assets = [
        path
        for path in source_files
        if path.relative_to(edition_dir).parts[0] == "assets" and path not in media_files
    ]

    narrative = {
        "schema": NARRATIVE_SCHEMA,
        "edition_id": slug,
        "format": "plain-text-snapshot",
        "pages": [_page_snapshot(path, edition_dir) for path in pages],
    }
    narrative_content = _write_if_changed(edition_dir / "narrative.json", narrative)
    narrative_sha256 = hashlib.sha256(narrative_content).hexdigest()

    dataset_pairs = [_dataset_resource(path, edition_dir) for path in data_files]
    data_resources = [resource for resource, _ in dataset_pairs]
    cold_candidates = [source for _, source in dataset_pairs if source is not None]
    figure_resources = compact_edition_figures(edition_dir)
    media_resources = [_resource(path, edition_dir) for path in media_files]
    route_resources = [
        {
            "path": page.relative_to(edition_dir).as_posix(),
            "title": next(
                snapshot["title"]
                for snapshot in narrative["pages"]
                if snapshot["path"] == page.relative_to(edition_dir).as_posix()
            ),
        }
        for page in pages
    ]
    source_bytes = sum(len(_integrity_bytes(path)) for path in source_files)
    data_bytes = sum(resource["bytes"] for resource in data_resources)
    media_bytes = sum(resource["bytes"] for resource in media_resources)
    legacy_asset_bytes = sum(len(_integrity_bytes(path)) for path in legacy_assets)

    manifest: dict[str, Any] = {
        "schema": EDITION_SCHEMA,
        "generator": BUNDLE_GENERATOR_VERSION,
        "id": slug,
        "kind": kind,
        "window": {
            "start": start,
            "end": end,
            "timezone": timezone_name,
        },
        "location": {
            "name": location_name,
            "latitude": latitude,
            "longitude": longitude,
        },
        "renderer": RENDERER_VERSION,
        "immutability": {
            "frozen": True,
            "source_tree_sha256": source_tree_sha256,
            "source_file_count": len(source_files),
        },
        "routes": route_resources,
        "narrative": {
            "path": "narrative.json",
            "bytes": len(narrative_content),
            "sha256": narrative_sha256,
        },
        "datasets": data_resources,
        "evidence": {
            "status": "self-contained" if data_resources else "legacy-rendered-only",
            "dataset_count": len(data_resources),
        },
        "figures": figure_resources,
        "media": [
            {**resource, "retention": "legacy-hot"} for resource in media_resources
        ],
        "legacy": {
            "source_tree_bytes": source_bytes,
            "rendered_asset_bytes": legacy_asset_bytes,
            "rendered_asset_count": len(legacy_assets),
            "shared_figure_source_bytes": sum(
                resource["source_bytes"] for resource in figure_resources
            ),
            "cold_candidates": cold_candidates,
        },
        "integrity": {
            "content_sha256": _content_digest(
                [*data_resources, *figure_resources, *media_resources],
                narrative_sha256,
            )
        },
        "budget": {
            "core_bytes": 0,
            "limit_bytes": CORE_SIZE_BUDGETS[kind],
            "status": "within",
            "media_bytes": media_bytes,
            "figure_bytes": sum(
                resource["bytes"] for resource in figure_resources
            ),
        },
    }

    # The manifest contributes to its own core size. Iterate until the byte count
    # encoded in the JSON is stable; this normally converges on the second pass.
    for _ in range(8):
        manifest_content = _json_bytes(manifest)
        core_bytes = (
            len(manifest_content)
            + len(narrative_content)
            + data_bytes
            + sum(resource["bytes"] for resource in figure_resources)
        )
        status = "within" if core_bytes <= CORE_SIZE_BUDGETS[kind] else "exceeded"
        if (
            manifest["budget"]["core_bytes"] == core_bytes
            and manifest["budget"]["status"] == status
        ):
            break
        manifest["budget"]["core_bytes"] = core_bytes
        manifest["budget"]["status"] = status

    _write_if_changed(manifest_path, manifest)
    return manifest_path


def _safe_resource_path(root: Path, relative: str) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        return None
    return resolved


def validate_edition_bundle(edition_dir: Path) -> BundleValidation:
    errors: list[str] = []
    manifest_path = edition_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return BundleValidation((f"Unreadable manifest: {exc}",), 0, 0)

    if manifest.get("schema") != EDITION_SCHEMA:
        errors.append(f"Unsupported manifest schema: {manifest.get('schema')!r}")
    if manifest.get("generator") != BUNDLE_GENERATOR_VERSION:
        errors.append(f"Unsupported bundle generator: {manifest.get('generator')!r}")
    if manifest.get("id") != edition_dir.name:
        errors.append("Manifest id does not match its directory")

    source_files = _source_files(edition_dir)
    immutable = manifest.get("immutability", {})
    if immutable.get("frozen") is not True:
        errors.append("Edition is not marked immutable")
    if immutable.get("source_file_count") != len(source_files):
        errors.append("Frozen source file count changed")
    if immutable.get("source_tree_sha256") != _source_tree_digest(
        source_files, edition_dir
    ):
        errors.append("Frozen source tree digest changed")

    references = [
        manifest.get("narrative", {}),
        *manifest.get("datasets", []),
        *manifest.get("figures", []),
        *manifest.get("media", []),
    ]
    validated_resources: list[dict[str, Any]] = []
    for resource in references:
        relative = resource.get("path")
        if not isinstance(relative, str):
            errors.append("Resource is missing a path")
            continue
        path = _safe_resource_path(edition_dir, relative)
        if path is None:
            errors.append(f"Unsafe resource path: {relative}")
            continue
        if not path.is_file():
            errors.append(f"Missing resource: {relative}")
            continue
        actual_content = _integrity_bytes(path)
        actual_bytes = len(actual_content)
        if actual_bytes != resource.get("bytes"):
            errors.append(f"Size mismatch: {relative}")
        actual_sha256 = hashlib.sha256(actual_content).hexdigest()
        if actual_sha256 != resource.get("sha256"):
            errors.append(f"Checksum mismatch: {relative}")
        validated_resources.append(
            {
                "path": relative,
                "bytes": actual_bytes,
                "sha256": actual_sha256,
            }
        )

    budget = manifest.get("budget", {})
    narrative = manifest.get("narrative", {})
    datasets = manifest.get("datasets", [])
    figures = manifest.get("figures", [])
    core_bytes = (
        len(_integrity_bytes(manifest_path))
        + int(narrative.get("bytes", 0))
        + sum(int(resource.get("bytes", 0)) for resource in datasets)
        + sum(int(resource.get("bytes", 0)) for resource in figures)
    )
    if int(budget.get("core_bytes", 0)) != core_bytes:
        errors.append("Recorded core size does not match bundle files")
    limit_bytes = int(budget.get("limit_bytes", 0))
    expected_status = "within" if core_bytes <= limit_bytes else "exceeded"
    if budget.get("status") != expected_status:
        errors.append("Bundle budget status is inconsistent")
    if expected_status == "exceeded":
        errors.append(
            f"Core size budget exceeded: {core_bytes} bytes > {limit_bytes} bytes"
        )

    if validated_resources:
        narrative_resource = validated_resources[0]
        content_resources = validated_resources[1:]
        content_sha256 = _content_digest(
            content_resources,
            narrative_resource["sha256"],
        )
        if manifest.get("integrity", {}).get("content_sha256") != content_sha256:
            errors.append("Bundle content digest does not match its resources")
    return BundleValidation(tuple(errors), core_bytes, limit_bytes)


def build_archive_catalog(
    saved: dict[str, list[Path]],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for collection in ("daily", "periods", "weeks"):
        for edition_dir in saved.get(collection, []):
            manifest_path = edition_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if collection == "periods" and (
                edition_dir / "analysis" / "index.html"
            ).is_file():
                href = f"periods/{edition_dir.name}/analysis/index.html"
            else:
                href = f"{collection}/{edition_dir.name}/index.html"
            entries.append(
                {
                    "id": manifest["id"],
                    "kind": manifest["kind"],
                    "start": manifest["window"]["start"],
                    "end": manifest["window"]["end"],
                    "href": href,
                    "manifest_href": f"{collection}/{edition_dir.name}/manifest.json",
                    "renderer": manifest["renderer"],
                    "core_bytes": manifest["budget"]["core_bytes"],
                    "media_bytes": manifest["budget"]["media_bytes"],
                    "figure_bytes": manifest["budget"].get("figure_bytes", 0),
                    "budget_status": manifest["budget"]["status"],
                    "content_sha256": manifest["integrity"]["content_sha256"],
                }
            )
    entries.sort(
        key=lambda entry: (entry["end"], entry["kind"], entry["id"]),
        reverse=True,
    )
    return {
        "schema": CATALOG_SCHEMA,
        "renderer": RENDERER_VERSION,
        "entries": entries,
    }


def archive_size_report(saved: dict[str, list[Path]]) -> dict[str, Any]:
    editions: list[dict[str, Any]] = []
    for collection in ("daily", "periods", "weeks"):
        for edition_dir in saved.get(collection, []):
            manifest = json.loads(
                (edition_dir / "manifest.json").read_text(encoding="utf-8")
            )
            editions.append(
                {
                    "id": manifest["id"],
                    "kind": manifest["kind"],
                    "core_bytes": manifest["budget"]["core_bytes"],
                    "core_limit_bytes": manifest["budget"]["limit_bytes"],
                    "core_status": manifest["budget"]["status"],
                    "media_bytes": manifest["budget"]["media_bytes"],
                    "figure_bytes": manifest["budget"].get("figure_bytes", 0),
                    "shared_figure_source_bytes": manifest["legacy"].get(
                        "shared_figure_source_bytes", 0
                    ),
                    "legacy_source_bytes": manifest["legacy"]["source_tree_bytes"],
                }
            )
    return {
        "schema": "atlas.archive-size-report/1",
        "editions": editions,
        "totals": {
            "editions": len(editions),
            "core_bytes": sum(edition["core_bytes"] for edition in editions),
            "media_bytes": sum(edition["media_bytes"] for edition in editions),
            "figure_bytes": sum(edition["figure_bytes"] for edition in editions),
            "shared_figure_source_bytes": sum(
                edition["shared_figure_source_bytes"] for edition in editions
            ),
            "legacy_source_bytes": sum(
                edition["legacy_source_bytes"] for edition in editions
            ),
            "over_budget": sum(
                edition["core_status"] == "exceeded" for edition in editions
            ),
        },
    }
