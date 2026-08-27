from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


_HEAD_PATTERN = re.compile(r"<head\b[^>]*>(?P<body>.*?)</head\s*>", re.IGNORECASE | re.DOTALL)
_STYLE_PATTERN = re.compile(
    r"<style(?P<attrs>[^>]*)>(?P<css>.*?)</style\s*>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ArchiveStyleResult:
    documents: int
    externalized_blocks: int
    stylesheets: int
    inline_bytes_removed: int


def _head_style_matches(source: str) -> list[re.Match[str]]:
    head = _HEAD_PATTERN.search(source)
    if head is None:
        return []
    return list(_STYLE_PATTERN.finditer(source, head.start("body"), head.end("body")))


def _style_digest(css: str) -> str:
    return hashlib.sha256(css.encode("utf-8")).hexdigest()


def externalize_repeated_archive_styles(archive_dir: Path) -> ArchiveStyleResult:
    """Deduplicate repeated head styles without rewriting a byte of CSS.

    Styles remain in their original cascade position. Only blocks repeated across
    the deployed archive are replaced, and the linked file is their exact UTF-8
    content rather than a minified or normalized derivative.
    """

    documents = sorted(archive_dir.rglob("*.html"))
    sources = {path: path.read_text(encoding="utf-8") for path in documents}
    counts: Counter[str] = Counter()
    css_by_digest: dict[str, str] = {}
    for source in sources.values():
        for match in _head_style_matches(source):
            css = match.group("css")
            digest = _style_digest(css)
            counts[digest] += 1
            css_by_digest.setdefault(digest, css)

    repeated = {digest for digest, count in counts.items() if count > 1}
    styles_dir = archive_dir / "assets" / "styles"
    for digest in sorted(repeated):
        styles_dir.mkdir(parents=True, exist_ok=True)
        path = styles_dir / f"{digest}.css"
        content = css_by_digest[digest].encode("utf-8")
        if not path.is_file() or path.read_bytes() != content:
            path.write_bytes(content)

    externalized = 0
    removed_bytes = 0
    for path, source in sources.items():
        matches = _head_style_matches(source)
        if not matches:
            continue
        replacements: list[tuple[int, int, str]] = []
        for match in matches:
            css = match.group("css")
            digest = _style_digest(css)
            if digest not in repeated:
                continue
            stylesheet = styles_dir / f"{digest}.css"
            href = Path(os.path.relpath(stylesheet, path.parent)).as_posix()
            attrs = match.group("attrs")
            replacement = (
                f'<link rel="stylesheet" href="{href}"{attrs} '
                f'data-atlas-style-sha256="{digest}">'
            )
            replacements.append((match.start(), match.end(), replacement))
            externalized += 1
            removed_bytes += len(css.encode("utf-8"))
        if replacements:
            rewritten = source
            for start, end, replacement in reversed(replacements):
                rewritten = rewritten[:start] + replacement + rewritten[end:]
            path.write_text(rewritten, encoding="utf-8")

    return ArchiveStyleResult(
        documents=len(documents),
        externalized_blocks=externalized,
        stylesheets=len(repeated),
        inline_bytes_removed=removed_bytes,
    )
