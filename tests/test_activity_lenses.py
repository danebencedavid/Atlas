from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from atlas.activity_lenses import activity_lens_json_bytes
from atlas.activity_lenses import ActivityLensError
from atlas.activity_lenses import available_lens_ids
from atlas.activity_lenses import evaluate_activity_lenses
from atlas.activity_lenses import lens_by_id
from atlas.activity_lenses import write_activity_lens_evidence


TIMEZONE = "Europe/Budapest"


def _day_frame(day: str = "2026-08-26") -> pd.DataFrame:
    start = pd.Timestamp(day, tz=TIMEZONE).tz_convert("UTC")
    end = (pd.Timestamp(day, tz=TIMEZONE) + pd.DateOffset(days=1)).tz_convert("UTC")
    times = pd.date_range(start, end, freq="h", inclusive="left")
    daylight = np.where((times.tz_convert(TIMEZONE).hour >= 6) & (times.tz_convert(TIMEZONE).hour < 19), 1, 0)
    return pd.DataFrame(
        {
            "time": times,
            "temperature_2m": 20.0,
            "relative_humidity_2m": 50.0,
            "precipitation": 0.0,
            "wind_speed_10m": 3.0,
            "wind_gusts_10m": 5.0,
            "cloud_cover": 20.0,
            "shortwave_radiation": daylight * 350.0,
            "sunshine_duration": daylight * 3600.0,
            "et0_fao_evapotranspiration": daylight * 0.12,
        }
    )


def _evaluate(frame: pd.DataFrame) -> dict:
    return evaluate_activity_lenses(
        frame,
        TIMEZONE,
        energy={"solar_index": 92.0},
        physical_energy={"pv_yield_kwh_per_kwp": 5.1},
    )


def test_mild_dry_day_produces_available_transparent_lenses() -> None:
    document = _evaluate(_day_frame())

    assert document["schema"] == "atlas.activity-lenses/1"
    assert document["scope"] == "completed-observed-day"
    assert document["date"] == "2026-08-26"
    assert document["evidence_quality"] == {
        "expected_hours": 24,
        "observed_hours": 24,
        "coverage": 1.0,
        "minimum_lens_coverage": 0.9,
    }
    assert available_lens_ids() == (
        "cycling",
        "walking",
        "outdoor_commute",
        "gardening",
        "solar_energy",
        "outdoor_comfort",
    )
    assert all(lens["status"] == "available" for lens in document["lenses"])
    assert all(lens["rating"] == "favorable" for lens in document["lenses"])
    assert lens_by_id(document, "cycling")["score"] == 100
    assert lens_by_id(document, "solar_energy")["evidence"]["solar_index"] == {
        "value": 92.0,
        "unit": "index",
        "coverage": 1.0,
        "sources": ["daily_energy.solar_index"],
    }
    assert "not forecasts" in document["disclaimer"]


def test_wet_windy_hot_day_explains_each_deduction() -> None:
    frame = _day_frame()
    frame["temperature_2m"] = 36.0
    frame["relative_humidity_2m"] = 72.0
    frame["precipitation"] = 1.0
    frame["wind_gusts_10m"] = 20.0

    document = evaluate_activity_lenses(
        frame,
        TIMEZONE,
        energy={"solar_index": 20.0},
        physical_energy={"pv_yield_kwh_per_kwp": 1.0},
    )

    cycling = lens_by_id(document, "cycling")
    assert cycling["rating"] == "difficult"
    assert cycling["score"] == 0
    assert {factor["rule"] for factor in cycling["limiting_factors"]} == {
        "cycling-rain",
        "cycling-wet-duration",
        "cycling-gusts",
        "cycling-heat",
    }
    assert all(factor["deduction"] > 0 for factor in cycling["limiting_factors"])

    comfort = lens_by_id(document, "outdoor_comfort")
    assert comfort["rating"] == "difficult"
    assert {factor["rule"] for factor in comfort["limiting_factors"]} == {
        "comfort-heat",
        "comfort-humid-heat",
    }
    assert lens_by_id(document, "solar_energy")["score"] == 45


def test_commute_lens_uses_only_declared_local_windows() -> None:
    frame = _day_frame()
    local_hours = pd.to_datetime(frame["time"], utc=True).dt.tz_convert(TIMEZONE).dt.hour
    frame.loc[(local_hours >= 11) & (local_hours < 14), "precipitation"] = 4.0

    document = _evaluate(frame)

    assert lens_by_id(document, "cycling")["rating"] == "mixed"
    commute = lens_by_id(document, "outdoor_commute")
    assert commute["rating"] == "favorable"
    assert commute["score"] == 100
    assert commute["evidence"]["precipitation_total_mm"]["value"] == 0.0
    assert document["commute_windows"] == ["06:00-10:00", "15:00-19:00"]


def test_sparse_required_evidence_withholds_only_affected_lenses() -> None:
    frame = _day_frame()
    frame.loc[:2, "wind_gusts_10m"] = np.nan

    document = _evaluate(frame)

    cycling = lens_by_id(document, "cycling")
    assert cycling["status"] == "insufficient-evidence"
    assert cycling["score"] is None
    assert cycling["missing_or_sparse_facts"] == ["wind_gust_max_ms"]
    assert cycling["evidence"]["wind_gust_max_ms"]["coverage"] == 0.875
    assert lens_by_id(document, "solar_energy")["status"] == "available"
    assert lens_by_id(document, "outdoor_comfort")["status"] == "available"


def test_solar_lens_never_guesses_without_normalized_energy_evidence() -> None:
    document = evaluate_activity_lenses(_day_frame(), TIMEZONE)

    solar = lens_by_id(document, "solar_energy")
    assert solar["status"] == "insufficient-evidence"
    assert solar["missing_or_sparse_facts"] == ["solar_index"]
    assert solar["score"] is None


def test_dst_day_uses_its_real_local_hour_count() -> None:
    document = _evaluate(_day_frame("2026-10-25"))

    assert document["date"] == "2026-10-25"
    assert document["evidence_quality"]["expected_hours"] == 25
    assert document["evidence_quality"]["observed_hours"] == 25
    assert document["evidence_quality"]["coverage"] == 1.0


def test_invalid_scope_and_unknown_lens_are_explicit() -> None:
    frame = pd.concat((_day_frame("2026-08-25"), _day_frame("2026-08-26")))

    with pytest.raises(ActivityLensError, match="one local calendar day"):
        _evaluate(frame)
    with pytest.raises(KeyError):
        lens_by_id(_evaluate(_day_frame()), "not-a-lens")


def test_serialization_is_deterministic_and_strict_json(tmp_path: Path) -> None:
    document = _evaluate(_day_frame())
    first = activity_lens_json_bytes(document)
    second = activity_lens_json_bytes(document)
    target = tmp_path / "activity-lenses.json"
    target.write_bytes(first)

    assert first == second
    assert first.endswith(b"\n")
    assert json.loads(target.read_text(encoding="utf-8")) == document


def test_daily_evidence_write_atomically_replaces_the_target(tmp_path: Path) -> None:
    target = tmp_path / "activity_lenses.json"
    target.write_text("stale edition data", encoding="utf-8")

    document = write_activity_lens_evidence(
        target,
        _day_frame(),
        TIMEZONE,
        energy={"solar_index": 92.0},
        physical_energy={"pv_yield_kwh_per_kwp": 5.1},
    )

    assert json.loads(target.read_text(encoding="utf-8")) == document
    assert document["date"] == "2026-08-26"
    assert list(tmp_path.iterdir()) == [target]
