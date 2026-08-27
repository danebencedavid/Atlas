from __future__ import annotations

import re
from pathlib import Path

from atlas.archive_styles import externalize_repeated_archive_styles


def test_repeated_head_css_is_externalized_byte_for_byte(tmp_path: Path):
    archive = tmp_path / "archive"
    nested = archive / "daily" / "2026-08-18"
    nested.mkdir(parents=True)
    exact_css = "\n  body { color: #123; }\n  @media (width < 40rem) { main { margin: 0; } }\n"
    unique_css = "main{display:grid}"
    first = archive / "index.html"
    second = nested / "index.html"
    first.write_text(
        f"<html><head><style>{exact_css}</style><style>{unique_css}</style></head>"
        "<body>root</body></html>",
        encoding="utf-8",
    )
    second.write_text(
        f"<html><head><style>{exact_css}</style></head><body>daily</body></html>",
        encoding="utf-8",
    )

    result = externalize_repeated_archive_styles(archive)

    assert result.documents == 2
    assert result.externalized_blocks == 2
    assert result.stylesheets == 1
    stylesheets = list((archive / "assets" / "styles").glob("*.css"))
    assert len(stylesheets) == 1
    assert stylesheets[0].read_bytes() == exact_css.encode("utf-8")
    first_html = first.read_text(encoding="utf-8")
    second_html = second.read_text(encoding="utf-8")
    assert f"<style>{unique_css}</style>" in first_html
    assert f"<style>{exact_css}</style>" not in first_html
    assert f"<style>{exact_css}</style>" not in second_html
    assert 'href="assets/styles/' in first_html
    assert 'href="../../assets/styles/' in second_html
    digest = re.search(r'data-atlas-style-sha256="([a-f0-9]{64})"', first_html)
    assert digest is not None
    assert stylesheets[0].stem == digest.group(1)


def test_body_style_is_not_moved_or_rewritten(tmp_path: Path):
    archive = tmp_path / "archive"
    archive.mkdir()
    body_style = "<style>.runtime { opacity: .5 }</style>"
    document = f"<html><head></head><body>{body_style}</body></html>"
    for name in ("one.html", "two.html"):
        (archive / name).write_text(document, encoding="utf-8")

    result = externalize_repeated_archive_styles(archive)

    assert result.externalized_blocks == 0
    assert (archive / "one.html").read_text(encoding="utf-8") == document
    assert (archive / "two.html").read_text(encoding="utf-8") == document
