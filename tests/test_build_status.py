from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from atlas.build_status import (
    WithheldStatusError,
    clear_withheld,
    prepare_recoveries,
    read_recovered,
    read_withheld,
    record_recovered,
    record_withheld,
    status_path,
)
from atlas.config import AtlasConfig, OutputConfig


def _config(tmp_path: Path) -> AtlasConfig:
    return AtlasConfig(outputs=OutputConfig(reports_dir=tmp_path / "reports"))


def test_a_withheld_build_leaves_a_durable_record(tmp_path):
    config = _config(tmp_path)
    assert read_withheld(config) == []
    record_withheld(config, date(2026, 8, 14), date(2026, 8, 16), "stale", shortfall_hours=22.17)
    stored = read_withheld(config)
    assert len(stored) == 1
    assert stored[0].period_end == "2026-08-16"
    assert stored[0].shortfall_hours == 22.17
    # Committed, because an ephemeral runner would otherwise take the evidence with it.
    assert status_path(config).is_file()


def test_the_notice_names_the_window_and_the_shortfall(tmp_path):
    config = _config(tmp_path)
    entry = record_withheld(
        config, date(2026, 8, 14), date(2026, 8, 16), "stale", shortfall_hours=22.17
    )
    described = entry.describe()
    assert "2026-08-14 to 2026-08-16" in described
    assert "22.2 h before the window closed" in described


def test_repeated_failures_on_one_window_stay_a_single_entry(tmp_path):
    config = _config(tmp_path)
    record_withheld(config, date(2026, 8, 14), date(2026, 8, 16), "first", shortfall_hours=22.0)
    record_withheld(config, date(2026, 8, 14), date(2026, 8, 16), "second", shortfall_hours=20.0)
    stored = read_withheld(config)
    # A daily retry must not bury the record under duplicates of one story.
    assert len(stored) == 1
    assert stored[0].shortfall_hours == 20.0


def test_withheld_attempt_becomes_a_linked_recovery_for_the_same_window(tmp_path):
    config = _config(tmp_path)
    record_withheld(
        config,
        date(2026, 8, 25),
        date(2026, 8, 27),
        "Station coverage 300/432; final day 12/144.",
        shortfall_hours=22.17,
    )

    recovery = prepare_recoveries(
        read_withheld(config),
        date(2026, 8, 25),
        date(2026, 8, 27),
        station_observed=144,
        station_expected=144,
        site_url="https://example.test/Atlas",
        workflow_url="https://github.com/example/Atlas/actions/runs/123",
        recovered_at="2026-08-28T16:38:11+00:00",
    )
    assert len(recovery) == 1
    record_recovered(config, recovery)

    assert read_withheld(config) == []
    stored = read_recovered(config)
    assert len(stored) == 1
    assert stored[0].station_observed == 144
    assert stored[0].station_expected == 144
    assert stored[0].workflow_url.endswith("/actions/runs/123")
    assert stored[0].report_url.endswith("/archive/daily/2026-08-27/")
    assert stored[0].data_url.endswith(
        "/archive/daily/2026-08-27/data/daily_station_observations.csv"
    )
    payload = json.loads(status_path(config).read_text(encoding="utf-8"))
    assert payload["withheld"] == []
    assert payload["recovered"][0]["recovered_at"] == "2026-08-28T16:38:11+00:00"


def test_recovery_does_not_leak_into_a_subsequent_window(tmp_path):
    config = _config(tmp_path)
    record_withheld(
        config,
        date(2026, 8, 25),
        date(2026, 8, 27),
        "incomplete",
    )

    later = prepare_recoveries(
        read_withheld(config),
        date(2026, 8, 26),
        date(2026, 8, 28),
        station_observed=144,
        station_expected=144,
        site_url="https://example.test/Atlas",
    )

    assert later == []
    assert len(read_withheld(config)) == 1


def test_separate_windows_are_kept_separately(tmp_path):
    config = _config(tmp_path)
    record_withheld(config, date(2026, 8, 14), date(2026, 8, 16), "a")
    record_withheld(config, date(2026, 8, 17), date(2026, 8, 19), "b")
    assert len(read_withheld(config)) == 2


def test_publishing_clears_the_pending_record(tmp_path):
    config = _config(tmp_path)
    record_withheld(config, date(2026, 8, 14), date(2026, 8, 16), "stale")
    clear_withheld(config)
    assert read_withheld(config) == []
    # The file remains, so the absence of pending items is itself explicit.
    assert json.loads(status_path(config).read_text(encoding="utf-8")) == {"withheld": []}


def test_a_corrupt_record_blocks_publication(tmp_path):
    config = _config(tmp_path)
    path = status_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(WithheldStatusError, match="publication is blocked"):
        read_withheld(config)


def test_a_schema_invalid_record_blocks_publication(tmp_path):
    config = _config(tmp_path)
    path = status_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"withheld": [{"period_start": "2026-08-14"}]}', encoding="utf-8")
    with pytest.raises(WithheldStatusError, match="publication is blocked"):
        read_withheld(config)


def test_a_wrongly_typed_record_blocks_publication(tmp_path):
    config = _config(tmp_path)
    path = status_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "withheld": [
                    {
                        "attempted_at": "2026-08-22T12:00:00+00:00",
                        "period_start": "2026-08-19",
                        "period_end": "2026-08-21",
                        "reason": "stale",
                        "shortfall_hours": "unknown",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(WithheldStatusError, match="publication is blocked"):
        read_withheld(config)
