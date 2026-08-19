from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from atlas.config import AtlasConfig, ForecastArchiveConfig, OutputConfig
from atlas.forecast_archive import (
    PREVIOUS_RUNS_URL,
    SCHEMA,
    CallBudget,
    _parse_live_forecast,
    _parse_previous_runs,
    availability_report,
    batch_variables,
    chunk_dates,
    fetch_previous_runs_window,
    read_archive,
    write_archive,
)


def _config(tmp_path: Path, **overrides) -> AtlasConfig:
    settings = {
        "lead_days": [1, 2],
        "models": ["best_match"],
        "variables": ["temperature_2m", "wind_speed_10m"],
        "archive_dir": tmp_path / "forecast_archive",
        "request_delay_seconds": 0.0,
        **overrides,
    }
    return AtlasConfig(
        forecast_archive=ForecastArchiveConfig(**settings),
        outputs=OutputConfig(data_dir=tmp_path / "data"),
    )


def _payload(keys: list[str], hours: int = 3) -> dict:
    times = [f"2026-08-0{1 + i // 24}T{i % 24:02d}:00" for i in range(hours)]
    return {"hourly": {"time": times, **{key: [1.5 + i for i in range(hours)] for key in keys}}}


def test_chunk_dates_covers_the_span_without_gaps_or_overlap():
    windows = chunk_dates(date(2024, 1, 22), date(2024, 2, 20), 14)
    assert windows[0] == (date(2024, 1, 22), date(2024, 2, 4))
    assert windows[-1][1] == date(2024, 2, 20)
    for earlier, later in zip(windows, windows[1:]):
        assert (later[0] - earlier[1]).days == 1
    assert chunk_dates(date(2024, 2, 1), date(2024, 1, 1), 14) == []


def test_batch_variables_respects_the_request_ceiling():
    batches = batch_variables([f"v{i}" for i in range(8)], 3)
    assert [len(batch) for batch in batches] == [3, 3, 2]
    assert sum(batches, []) == [f"v{i}" for i in range(8)]


def test_lead_time_is_the_previous_day_offset_in_hours():
    payload = _payload(["temperature_2m_previous_day1", "temperature_2m_previous_day3"])
    frame = _parse_previous_runs(
        payload, ["temperature_2m"], [1, 3], ["best_match"], datetime.now(timezone.utc)
    )
    assert set(frame["lead_time_hours"]) == {24, 72}


def test_multi_model_responses_are_split_by_model_suffix():
    payload = _payload(
        ["temperature_2m_previous_day1_ecmwf_ifs025", "temperature_2m_previous_day1_icon_seamless"]
    )
    frame = _parse_previous_runs(
        payload,
        ["temperature_2m"],
        [1],
        ["ecmwf_ifs025", "icon_seamless"],
        datetime.now(timezone.utc),
    )
    assert set(frame["model"]) == {"ecmwf_ifs025", "icon_seamless"}
    assert len(frame) == 6


def test_missing_series_and_nulls_are_dropped_not_counted():
    payload = {
        "hourly": {
            "time": ["2026-08-01T00:00", "2026-08-01T01:00"],
            "temperature_2m_previous_day1": [1.0, None],
            # day2 absent entirely, as an unavailable offset would be
        }
    }
    frame = _parse_previous_runs(
        payload, ["temperature_2m"], [1, 2], ["best_match"], datetime.now(timezone.utc)
    )
    assert len(frame) == 1
    assert frame["value"].iloc[0] == pytest.approx(1.0)


def test_parsed_frame_matches_the_declared_schema():
    payload = _payload(["temperature_2m_previous_day1"])
    frame = _parse_previous_runs(
        payload, ["temperature_2m"], [1], ["best_match"], datetime.now(timezone.utc)
    )
    assert list(frame.columns) == list(SCHEMA)
    assert str(frame["valid_time_utc"].dtype) == "datetime64[ns, UTC]"
    assert str(frame["lead_time_hours"].dtype) == "int16"


def test_valid_times_are_utc_even_though_the_api_returns_naive_strings():
    payload = _payload(["temperature_2m_previous_day1"])
    frame = _parse_previous_runs(
        payload, ["temperature_2m"], [1], ["best_match"], datetime.now(timezone.utc)
    )
    assert frame["valid_time_utc"].dt.tz is not None
    assert str(frame["valid_time_utc"].dt.tz) == "UTC"


def test_live_forecast_lead_time_is_measured_from_the_issue_time():
    issued = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    payload = {
        "hourly": {
            "time": ["2026-07-31T23:00", "2026-08-01T00:00", "2026-08-01T06:00"],
            "temperature_2m": [10.0, 11.0, 12.0],
        }
    }
    frame = _parse_live_forecast(payload, ["temperature_2m"], ["best_match"], issued)
    # The hour before issue is not a forecast and is dropped.
    assert list(frame["lead_time_hours"]) == [0, 6]


def test_requests_are_cached_and_never_refetched(tmp_path, monkeypatch):
    config = _config(tmp_path)
    calls: list[dict] = []

    def fake_fetch(url, params):
        calls.append(params)
        assert url == PREVIOUS_RUNS_URL
        # UTC must be requested explicitly; local time would misalign every pair.
        assert params["timezone"] == "UTC"
        return _payload(["temperature_2m_previous_day1", "temperature_2m_previous_day2"])

    monkeypatch.setattr("atlas.forecast_archive.fetch_json_with_retry", fake_fetch)
    budget = CallBudget(delay_seconds=0.0)
    first = fetch_previous_runs_window(
        config, date(2026, 8, 1), date(2026, 8, 2), ["temperature_2m"], budget
    )
    second = fetch_previous_runs_window(
        config, date(2026, 8, 1), date(2026, 8, 2), ["temperature_2m"], budget
    )
    assert len(calls) == 1
    assert budget.calls == 1
    assert budget.cache_hits == 1
    pd.testing.assert_frame_equal(first.drop(columns=["retrieved_at"]), second.drop(columns=["retrieved_at"]))


def test_wind_is_requested_in_metres_per_second(tmp_path, monkeypatch):
    config = _config(tmp_path)
    seen: dict = {}

    def fake_fetch(url, params):
        seen.update(params)
        return _payload(["wind_speed_10m_previous_day1"])

    monkeypatch.setattr("atlas.forecast_archive.fetch_json_with_retry", fake_fetch)
    fetch_previous_runs_window(
        config, date(2026, 8, 1), date(2026, 8, 2), ["wind_speed_10m"], CallBudget(delay_seconds=0.0)
    )
    assert seen["wind_speed_unit"] == "ms"


def test_call_budget_refuses_to_exceed_the_daily_limit():
    budget = CallBudget(delay_seconds=0.0, daily_limit=2)
    budget.record_call("one")
    budget.record_call("two")
    with pytest.raises(RuntimeError, match="calls/day"):
        budget.record_call("three")


def test_archive_round_trips_and_partitions_by_month(tmp_path):
    config = _config(tmp_path)
    times = pd.to_datetime(["2026-07-31T23:00Z", "2026-08-01T00:00Z"], utc=True)
    frame = pd.DataFrame(
        {
            "valid_time_utc": times,
            "lead_time_hours": [24, 24],
            "model": ["best_match", "best_match"],
            "variable": ["temperature_2m", "temperature_2m"],
            "value": [10.0, 11.0],
            "retrieved_at": pd.to_datetime(["2026-08-02T00:00Z"] * 2, utc=True),
        }
    )
    written = write_archive(config, frame, "backfill")
    assert {path.stem for path in written} == {"2026-07", "2026-08"}
    assert len(read_archive(config, "backfill")) == 2


def test_writing_is_append_only_and_repeat_writes_do_not_duplicate(tmp_path):
    config = _config(tmp_path)
    base = pd.DataFrame(
        {
            "valid_time_utc": pd.to_datetime(["2026-08-01T00:00Z"], utc=True),
            "lead_time_hours": [24],
            "model": ["best_match"],
            "variable": ["temperature_2m"],
            "value": [10.0],
            "retrieved_at": pd.to_datetime(["2026-08-02T00:00Z"], utc=True),
        }
    )
    write_archive(config, base, "backfill")
    write_archive(config, base, "backfill")
    assert len(read_archive(config, "backfill")) == 1

    # A later row for the same valid hour is added, and the original is preserved:
    # what was predicted at the time must never be overwritten.
    later = base.assign(
        value=[99.0], retrieved_at=pd.to_datetime(["2026-08-03T00:00Z"], utc=True)
    )
    write_archive(config, later, "backfill")
    stored = read_archive(config, "backfill")
    assert len(stored) == 2
    assert set(stored["value"]) == {10.0, 99.0}


def test_availability_report_counts_rows_per_variable_lead_and_model(tmp_path):
    frame = pd.DataFrame(
        {
            "valid_time_utc": pd.to_datetime(["2026-08-01T00:00Z"] * 3, utc=True),
            "lead_time_hours": [24, 48, 24],
            "model": ["best_match", "best_match", "icon_seamless"],
            "variable": ["temperature_2m", "temperature_2m", "temperature_2m"],
            "value": [1.0, 2.0, 3.0],
            "retrieved_at": pd.to_datetime(["2026-08-02T00:00Z"] * 3, utc=True),
        }
    )
    report = availability_report(frame)
    assert len(report) == 3
    assert set(report["rows"]) == {1}


def test_empty_archive_reads_back_with_the_schema(tmp_path):
    config = _config(tmp_path)
    frame = read_archive(config, "backfill")
    assert frame.empty
    assert list(frame.columns) == list(SCHEMA)
