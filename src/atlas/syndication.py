"""Atom feed, sitemap and robots policy for the published Atlas site.

Atlas publishes a new edition every day and, until now, offered no way to follow
it: a reader had to remember to come back, and a crawler had no inventory of the
archive. These three files are generated from the same archive catalogue the
Archive page is built from, so they can never describe editions that are not
actually published.

One property matters more than completeness here. A feed reader treats a changed
``updated`` stamp as "this was revised", so a feed rebuilt daily must not restamp
entries that did not change. Every timestamp below therefore comes from the
edition's own reporting window, never from the build clock. A rebuilt feed for an
unchanged archive is byte-identical.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from xml.dom import minidom
from zoneinfo import ZoneInfo

from atlas.config import AtlasConfig


ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"

# Entries a feed reader shows at once. The archive itself stays complete in the
# sitemap; a feed is a notification surface, not a catalogue.
FEED_ENTRY_LIMIT = 40

_KIND_LABELS = {
    "daily": "Daily report",
    "periods": "72-hour analysis",
    "weeks": "Weekly report",
}


@dataclass(frozen=True)
class SyndicationEntry:
    """One published edition, reduced to what a feed or sitemap needs."""

    collection: str
    slug: str
    start: str
    end: str
    href: str
    date_label: str
    title: str
    summary: str
    closed_at: datetime


def _period_close(end: str, timezone_name: str) -> datetime:
    """The instant the described period finished.

    Atlas reports completed local periods, so an edition's content time is the
    end of its final local day rather than whenever the build happened to run.
    Using the window keeps the feed stable across rebuilds and keeps the ordering
    of entries identical to the ordering of the weather they describe.
    """

    closing_day = datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)
    return datetime.combine(
        closing_day, time(0, 0), tzinfo=ZoneInfo(timezone_name)
    )


def _edition_briefing(source: Path, collection: str) -> tuple[str, str]:
    """The regime label and briefing a frozen edition already states."""

    candidates = (
        ("data/daily_summary.json",)
        if collection == "daily"
        else ("data/summary.json", "data/daily_summary.json")
    )
    for relative in candidates:
        path = source / relative
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        regime = payload.get("regime") or {}
        label = str(regime.get("label") or "").strip()
        briefing = str(regime.get("briefing") or "").strip()
        if label or briefing:
            return label, briefing
    return "", ""


def build_syndication_entries(
    config: AtlasConfig,
    archive_entries: Iterable[dict[str, Any]],
) -> list[SyndicationEntry]:
    """Reduce archive catalogue rows to syndication entries, newest first."""

    timezone_name = config.location.timezone
    place = config.location.name
    entries: list[SyndicationEntry] = []
    for row in archive_entries:
        collection = str(row["collection"])
        label, briefing = _edition_briefing(Path(row["source"]), collection)
        kind = _KIND_LABELS.get(collection, "Report")
        # The Archive page separates a date range with a hyphen; a feed title
        # already carries an em dash before the regime, so the range gets an en
        # dash to keep the two separators visually distinct in a reader's list.
        date_label = str(row["date_label"]).replace(" - ", " – ")
        headline = f"{place}, {date_label}"
        if label:
            headline = f"{headline} — {label}"
        summary = briefing or (
            f"{kind} for {date_label}. Observed conditions in {place}, "
            f"{config.location.region}."
        )
        entries.append(
            SyndicationEntry(
                collection=collection,
                slug=str(row["slug"]),
                start=str(row["start"]),
                end=str(row["end"]),
                href=str(row["href"]),
                date_label=date_label,
                title=f"{headline} ({kind})",
                summary=summary,
                closed_at=_period_close(str(row["end"]), timezone_name),
            )
        )
    entries.sort(key=lambda entry: (entry.closed_at, entry.slug), reverse=True)
    return entries


def _pretty_xml(root: ET.Element) -> bytes:
    raw = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8")


def write_atom_feed(
    config: AtlasConfig,
    entries: list[SyndicationEntry],
    site_dir: Path,
    *,
    limit: int = FEED_ENTRY_LIMIT,
) -> Path:
    """Write ``feed.xml``: the most recent editions, newest first."""

    origin = config.project.site_url.rstrip("/")
    published = entries[:limit]
    ET.register_namespace("", ATOM_NAMESPACE)
    feed = ET.Element(f"{{{ATOM_NAMESPACE}}}feed")
    ET.SubElement(feed, f"{{{ATOM_NAMESPACE}}}id").text = f"{origin}/"
    ET.SubElement(feed, f"{{{ATOM_NAMESPACE}}}title").text = (
        f"{config.project.name} — {config.location.name} weather, placed in context"
    )
    ET.SubElement(feed, f"{{{ATOM_NAMESPACE}}}subtitle").text = config.project.tagline
    ET.SubElement(
        feed,
        f"{{{ATOM_NAMESPACE}}}link",
        {"rel": "alternate", "type": "text/html", "href": f"{origin}/"},
    )
    ET.SubElement(
        feed,
        f"{{{ATOM_NAMESPACE}}}link",
        {"rel": "self", "type": "application/atom+xml", "href": f"{origin}/feed.xml"},
    )
    # The newest edition's own window, so an unchanged archive yields an
    # unchanged feed rather than one that looks revised on every rebuild.
    feed_updated = (
        published[0].closed_at if published else _period_close("1970-01-01", "UTC")
    )
    ET.SubElement(feed, f"{{{ATOM_NAMESPACE}}}updated").text = feed_updated.isoformat()
    author = ET.SubElement(feed, f"{{{ATOM_NAMESPACE}}}author")
    ET.SubElement(author, f"{{{ATOM_NAMESPACE}}}name").text = config.project.name
    ET.SubElement(author, f"{{{ATOM_NAMESPACE}}}uri").text = f"{origin}/"
    ET.SubElement(feed, f"{{{ATOM_NAMESPACE}}}rights").text = (
        "Atlas describes completed weather periods. It is not a forecast, warning "
        "service or substitute for official safety information."
    )

    for entry in published:
        url = f"{origin}/archive/{entry.href}"
        element = ET.SubElement(feed, f"{{{ATOM_NAMESPACE}}}entry")
        ET.SubElement(element, f"{{{ATOM_NAMESPACE}}}id").text = url
        ET.SubElement(element, f"{{{ATOM_NAMESPACE}}}title").text = entry.title
        ET.SubElement(
            element,
            f"{{{ATOM_NAMESPACE}}}link",
            {"rel": "alternate", "type": "text/html", "href": url},
        )
        ET.SubElement(element, f"{{{ATOM_NAMESPACE}}}updated").text = (
            entry.closed_at.isoformat()
        )
        ET.SubElement(element, f"{{{ATOM_NAMESPACE}}}published").text = (
            entry.closed_at.isoformat()
        )
        ET.SubElement(
            element,
            f"{{{ATOM_NAMESPACE}}}category",
            {"term": entry.collection, "label": _KIND_LABELS.get(entry.collection, "")},
        )
        ET.SubElement(
            element, f"{{{ATOM_NAMESPACE}}}summary", {"type": "text"}
        ).text = entry.summary

    target = site_dir / "feed.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_pretty_xml(feed))
    return target


def write_sitemap(
    config: AtlasConfig,
    entries: list[SyndicationEntry],
    site_dir: Path,
    *,
    live_pages: Iterable[str],
) -> Path:
    """Write ``sitemap.xml`` covering the live pages and every online edition.

    Cold-archive editions keep a landing page describing the download, so they
    belong here too: the page is real, reachable and worth indexing even though
    the edition's own files now live in a verified release asset.
    """

    origin = config.project.site_url.rstrip("/")
    ET.register_namespace("", SITEMAP_NAMESPACE)
    urlset = ET.Element(f"{{{SITEMAP_NAMESPACE}}}urlset")
    newest = entries[0].closed_at if entries else None

    def add(location: str, last_modified: datetime | None) -> None:
        element = ET.SubElement(urlset, f"{{{SITEMAP_NAMESPACE}}}url")
        ET.SubElement(element, f"{{{SITEMAP_NAMESPACE}}}loc").text = location
        if last_modified is not None:
            ET.SubElement(element, f"{{{SITEMAP_NAMESPACE}}}lastmod").text = (
                last_modified.date().isoformat()
            )

    # The live pages always describe the newest edition, so they share its date.
    for page in live_pages:
        suffix = "" if page in {"", "index.html"} else page
        add(f"{origin}/{suffix}", newest)
    for entry in entries:
        add(f"{origin}/archive/{entry.href}", entry.closed_at)

    target = site_dir / "sitemap.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_pretty_xml(urlset))
    return target


def write_robots(config: AtlasConfig, site_dir: Path) -> Path:
    """Write ``robots.txt``: open to crawlers, pointing at the sitemap."""

    origin = config.project.site_url.rstrip("/")
    target = site_dir / "robots.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(
            (
                "User-agent: *",
                "Allow: /",
                f"Sitemap: {origin}/sitemap.xml",
                "",
            )
        ),
        encoding="utf-8",
    )
    return target
