from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from atlas.config import AtlasConfig
from atlas.syndication import ATOM_NAMESPACE
from atlas.syndication import SITEMAP_NAMESPACE
from atlas.syndication import build_syndication_entries
from atlas.syndication import write_atom_feed
from atlas.syndication import write_robots
from atlas.syndication import write_sitemap


def _edition(root: Path, collection: str, slug: str, label: str) -> Path:
    source = root / collection / slug
    (source / "data").mkdir(parents=True)
    name = "daily_summary.json" if collection == "daily" else "summary.json"
    (source / "data" / name).write_text(
        json.dumps(
            {
                "regime": {
                    "label": label,
                    "briefing": f"{label}: temperature was -1.6 deg C versus normal.",
                }
            }
        ),
        encoding="utf-8",
    )
    return source


def _rows(root: Path) -> list[dict[str, object]]:
    return [
        {
            "collection": "daily",
            "slug": "2026-10-15",
            "start": "2026-10-15",
            "end": "2026-10-15",
            "href": "daily/2026-10-15/index.html",
            "date_label": "15 October 2026",
            "source": _edition(root, "daily", "2026-10-15", "Mixed transition period"),
        },
        {
            "collection": "periods",
            "slug": "2026-10-13_2026-10-15",
            "start": "2026-10-13",
            "end": "2026-10-15",
            "href": "periods/2026-10-13_2026-10-15/analysis/index.html",
            "date_label": "13 October 2026 - 15 October 2026",
            "source": _edition(
                root, "periods", "2026-10-13_2026-10-15", "Wet frontal period"
            ),
        },
        {
            "collection": "daily",
            "slug": "2026-09-30",
            "start": "2026-09-30",
            "end": "2026-09-30",
            "href": "daily/2026-09-30/index.html",
            "date_label": "30 September 2026",
            "source": _edition(root, "daily", "2026-09-30", "Dry anticyclonic period"),
        },
    ]


def test_entries_are_newest_first_and_carry_the_edition_briefing(tmp_path: Path):
    config = AtlasConfig()
    entries = build_syndication_entries(config, _rows(tmp_path))

    assert [entry.slug for entry in entries][-1] == "2026-09-30"
    assert entries[0].closed_at >= entries[1].closed_at
    briefings = {entry.slug: entry.summary for entry in entries}
    assert briefings["2026-10-15"].startswith("Mixed transition period:")
    assert briefings["2026-10-13_2026-10-15"].startswith("Wet frontal period:")
    titles = {entry.slug: entry.title for entry in entries}
    assert titles["2026-10-15"] == (
        "Debrecen, 15 October 2026 — Mixed transition period (Daily report)"
    )
    # A date range reads as a range rather than as a subtraction.
    assert "13 October 2026 – 15 October 2026" in titles["2026-10-13_2026-10-15"]


def test_entry_timestamps_come_from_the_reporting_window_not_the_build(tmp_path: Path):
    """A rebuilt feed must not look revised.

    Feed readers treat a changed ``updated`` as a revision, so stamping entries
    with the build clock would re-notify every subscriber about every edition on
    every daily build. The stamp is the close of the edition's final local day.
    """

    config = AtlasConfig()
    entries = build_syndication_entries(config, _rows(tmp_path))
    daily = next(entry for entry in entries if entry.slug == "2026-10-15")

    assert daily.closed_at.isoformat() == "2026-10-16T00:00:00+02:00"

    first = write_atom_feed(config, entries, tmp_path / "a").read_bytes()
    second = write_atom_feed(config, entries, tmp_path / "b").read_bytes()
    assert first == second


def test_atom_feed_is_well_formed_and_self_describing(tmp_path: Path):
    config = AtlasConfig()
    entries = build_syndication_entries(config, _rows(tmp_path))
    feed_path = write_atom_feed(config, entries, tmp_path / "site")

    root = ET.parse(feed_path).getroot()
    assert root.tag == f"{{{ATOM_NAMESPACE}}}feed"
    links = {
        element.get("rel"): element.get("href")
        for element in root.findall(f"{{{ATOM_NAMESPACE}}}link")
    }
    assert links["self"] == "https://danebencedavid.github.io/Atlas/feed.xml"
    assert links["alternate"] == "https://danebencedavid.github.io/Atlas/"

    atom_entries = root.findall(f"{{{ATOM_NAMESPACE}}}entry")
    assert len(atom_entries) == 3
    for element in atom_entries:
        # Every Atom entry needs a stable id, a title and an updated stamp.
        for field in ("id", "title", "updated"):
            assert element.findtext(f"{{{ATOM_NAMESPACE}}}{field}")
        href = element.find(f"{{{ATOM_NAMESPACE}}}link").get("href")
        assert href.startswith("https://danebencedavid.github.io/Atlas/archive/")
        assert element.findtext(f"{{{ATOM_NAMESPACE}}}id") == href
    # Atlas is not a forecast service, and a feed strips the page that says so.
    assert "not a forecast" in root.findtext(f"{{{ATOM_NAMESPACE}}}rights")


def test_feed_entry_count_is_capped_while_the_sitemap_stays_complete(tmp_path: Path):
    config = AtlasConfig()
    rows = _rows(tmp_path)
    feed_path = write_atom_feed(config, build_syndication_entries(config, rows), tmp_path / "s", limit=2)
    root = ET.parse(feed_path).getroot()
    assert len(root.findall(f"{{{ATOM_NAMESPACE}}}entry")) == 2

    sitemap_path = write_sitemap(
        config,
        build_syndication_entries(config, rows),
        tmp_path / "s",
        live_pages=["", "report.html", "archive/"],
    )
    urls = [
        element.findtext(f"{{{SITEMAP_NAMESPACE}}}loc")
        for element in ET.parse(sitemap_path).getroot()
    ]
    origin = "https://danebencedavid.github.io/Atlas"
    assert urls[:3] == [f"{origin}/", f"{origin}/report.html", f"{origin}/archive/"]
    # Every edition is listed, including the ones the feed trimmed.
    assert len(urls) == 3 + len(rows)
    assert f"{origin}/archive/daily/2026-09-30/index.html" in urls


def test_sitemap_lastmod_tracks_each_edition(tmp_path: Path):
    config = AtlasConfig()
    entries = build_syndication_entries(config, _rows(tmp_path))
    sitemap_path = write_sitemap(
        config, entries, tmp_path / "s", live_pages=[""]
    )
    modified = {
        element.findtext(f"{{{SITEMAP_NAMESPACE}}}loc"): element.findtext(
            f"{{{SITEMAP_NAMESPACE}}}lastmod"
        )
        for element in ET.parse(sitemap_path).getroot()
    }
    origin = "https://danebencedavid.github.io/Atlas"
    assert modified[f"{origin}/archive/daily/2026-09-30/index.html"] == "2026-10-01"
    assert modified[f"{origin}/archive/daily/2026-10-15/index.html"] == "2026-10-16"
    # The live pages describe the newest edition, so they carry its date.
    assert modified[f"{origin}/"] == "2026-10-16"


def test_missing_briefing_falls_back_without_inventing_weather(tmp_path: Path):
    config = AtlasConfig()
    source = tmp_path / "daily" / "2026-10-15"
    source.mkdir(parents=True)
    entries = build_syndication_entries(
        config,
        [
            {
                "collection": "daily",
                "slug": "2026-10-15",
                "start": "2026-10-15",
                "end": "2026-10-15",
                "href": "daily/2026-10-15/index.html",
                "date_label": "15 October 2026",
                "source": source,
            }
        ],
    )

    assert len(entries) == 1
    summary = entries[0].summary
    assert "15 October 2026" in summary
    assert "Debrecen" in summary
    # No regime evidence means no regime claim, not a plausible-sounding one.
    assert "period" not in entries[0].title.lower().replace("report", "")
    assert entries[0].title == "Debrecen, 15 October 2026 (Daily report)"


def test_robots_points_crawlers_at_the_sitemap(tmp_path: Path):
    config = AtlasConfig()
    content = write_robots(config, tmp_path / "site").read_text(encoding="utf-8")

    assert "User-agent: *" in content
    assert "Allow: /" in content
    assert "Sitemap: https://danebencedavid.github.io/Atlas/sitemap.xml" in content
