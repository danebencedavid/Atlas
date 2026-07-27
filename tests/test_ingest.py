from datetime import date

import pandas as pd

from atlas.config import AtlasConfig
from atlas.ingest import fetch_open_meteo_week


def test_fetch_open_meteo_week_filters_to_local_calendar_week(tmp_path, monkeypatch):
    captured = {}
    times = pd.date_range("2026-07-19 00:00", periods=240, freq="h", tz="UTC")

    def fake_fetch(_url, params):
        captured.update(params)
        return {
            "hourly": {
                "time": [timestamp.strftime("%Y-%m-%dT%H:%M") for timestamp in times],
                "temperature_2m": [20.0] * len(times),
            }
        }

    monkeypatch.setattr("atlas.ingest.fetch_json_with_retry", fake_fetch)

    frame = fetch_open_meteo_week(
        AtlasConfig(),
        date(2026, 7, 20),
        date(2026, 7, 26),
        data_dir=tmp_path,
        refresh=True,
    )

    assert captured["start_date"] == "2026-07-19"
    assert captured["end_date"] == "2026-07-26"
    assert len(frame) == 168
    assert frame["time"].min() == pd.Timestamp("2026-07-19 22:00", tz="UTC")
    assert frame["time"].max() == pd.Timestamp("2026-07-26 21:00", tz="UTC")
