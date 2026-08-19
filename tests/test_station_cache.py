"""Regression tests for the HungaroMet station cache keys.

The bug these cover: the recent station file lives at one fixed URL and rolls
forward in place, but its cache key was built from the caller's requested start
year. The same resource was therefore stored under several names holding
different vintages, and which vintage a caller got depended on the period asked
for rather than on the data.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from atlas.config import AtlasConfig, HungaroMetConfig, OutputConfig
from atlas.hungaromet import fetch_station_observations


def _config(tmp_path: Path) -> AtlasConfig:
    return AtlasConfig(
        hungaromet=HungaroMetConfig(station_id=64711),
        outputs=OutputConfig(data_dir=tmp_path / "data"),
    )


def _zip_payload(last_day: str) -> bytes:
    """A minimal station export covering 2024-01-01 through ``last_day``."""
    times = pd.date_range("2024-01-01", last_day, freq="10min", tz="UTC")
    header = "StationNumber;Time;r;t;v;p;u;fs;fsd;fx"
    rows = [
        f"64711;{stamp.strftime('%Y%m%d%H%M')};0.0;10.0;10000;1013.0;70.0;3.0;180;6.0"
        for stamp in times
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("HABP_10M_64711_akt.csv", "\n".join([header, *rows]))
    return buffer.getvalue()


def test_requested_start_year_does_not_select_a_cache_vintage(tmp_path, monkeypatch):
    """The regression: two callers, two start years, one URL, one answer.

    Before the fix, the 2024 call and the 2026 call wrote different files and a
    later caller could be served either, depending only on the period it asked
    for.
    """
    config = _config(tmp_path)
    downloads: list[str] = []

    def fake_request(url: str, *args, **kwargs) -> bytes:
        downloads.append(url)
        # A rolling resource: whatever it returns now is the current vintage.
        return _zip_payload("2026-08-18")

    monkeypatch.setattr("atlas.hungaromet._request_bytes", fake_request)

    early = fetch_station_observations(config, date(2024, 2, 1), date(2024, 2, 2))
    late = fetch_station_observations(config, date(2026, 8, 1), date(2026, 8, 2))

    assert not early.frame.empty
    assert not late.frame.empty
    # One resource, fetched once: the second call is a cache hit, not a second
    # file under a different name.
    assert len(downloads) == 1

    cached = sorted((tmp_path / "data" / "raw" / "hungaromet").glob("*.zip"))
    assert len(cached) == 1, f"one rolling resource must occupy one key, found {cached}"
    # The key names the resource and when it was fetched, not the period asked for.
    assert "recent" in cached[0].name
    assert "2024" not in cached[0].stem.replace("64711", "")


def test_cache_key_carries_the_retrieval_date(tmp_path, monkeypatch):
    """A new day is a new vintage, so it must not be served from yesterday's file."""
    config = _config(tmp_path)
    monkeypatch.setattr(
        "atlas.hungaromet._request_bytes", lambda url, *a, **k: _zip_payload("2026-08-18")
    )
    fetch_station_observations(config, date(2026, 8, 1), date(2026, 8, 2))
    cached = sorted((tmp_path / "data" / "raw" / "hungaromet").glob("*.zip"))
    assert len(cached) == 1
    stem = cached[0].stem
    # Ends with an ISO date, which is what makes tomorrow's fetch a different key.
    assert date.fromisoformat(stem[-10:])


def test_refresh_still_bypasses_the_cache(tmp_path, monkeypatch):
    config = _config(tmp_path)
    downloads: list[str] = []

    def fake_request(url: str, *args, **kwargs) -> bytes:
        downloads.append(url)
        return _zip_payload("2026-08-18")

    monkeypatch.setattr("atlas.hungaromet._request_bytes", fake_request)
    fetch_station_observations(config, date(2026, 8, 1), date(2026, 8, 2))
    fetch_station_observations(config, date(2026, 8, 1), date(2026, 8, 2), refresh=True)
    assert len(downloads) == 2
