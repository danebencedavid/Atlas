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
        energy={"solar_index": 92.0, "solar_evidence": {"status": "derived"}},
        physical_energy={"pv_yield_kwh_per_kwp": 5.1},
        solar_reference=_reference(frame),
    )


def _reference(frame: pd.DataFrame, mean: float = 4550 / 0.92) -> dict:
    day = pd.Timestamp(frame["time"].iloc[0]).tz_convert(TIMEZONE).date()
    return {
        "status": "derived", "date": day.isoformat(), "minimum_years": 24, "expected_years": 30,
        "samples": [{"date": f"{year}-{day.month:02}-{min(day.day, 28) if day.month == 2 else day.day:02}", "radiation_wh_m2": mean, "status": "valid"} for year in range(1991, 2021)],
        "provider": "test fixture", "product": "synthetic reference",
    }


def test_mild_dry_day_produces_available_transparent_lenses() -> None:
    document = _evaluate(_day_frame())

    assert document["schema"] == "atlas.activity-lenses/1"
    assert document["scope"] == "completed-historical-day"
    assert document["date"] == "2026-08-26"
    assert document["evidence_quality"] == {
        "expected_hours": 24,
        "present_hours": 24,
        "missing_slots": [],
        "duplicate_slots": [],
        "off_grid_timestamps": [],
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
    assert lens_by_id(document, "solar_energy")["evidence"]["seasonal_radiation_pct"] == {
        "value": 92.0,
        "unit": "% of seasonal normal",
        "coverage": 1.0,
        "sources": ["shortwave_radiation", "solar_reference"],
        "kind": "derived",
        "reason": None,
    }
    methodology = document["methodology"]
    assert methodology["base_score"] == 100
    assert methodology["score_floor"] == 0
    assert methodology["rating_bands"] == [
        {"rating": "favorable", "condition": "80-100"},
        {"rating": "mixed", "condition": "55-79"},
        {"rating": "difficult", "condition": "0-54"},
    ]
    cycling_method = next(
        lens for lens in methodology["lenses"] if lens["id"] == "cycling"
    )
    gust_rule = next(
        rule for rule in cycling_method["rules"] if rule["id"] == "cycling-gusts"
    )
    assert gust_rule["bands"][0]["condition"] == ">= 18 m/s"
    assert gust_rule["bands"][0]["deduction"] == 40
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
        energy={"solar_index": 20.0, "solar_evidence": {"status": "derived"}},
        physical_energy={"pv_yield_kwh_per_kwp": 1.0},
        solar_reference=_reference(frame, mean=22750),
    )

    cycling = lens_by_id(document, "cycling")
    assert cycling["rating"] == "difficult"
    assert cycling["score"] == 0
    assert {factor["rule"] for factor in cycling["limiting_factors"]} == {
        "cycling-rain",
        "cycling-gusts",
        "cycling-heat",
        "severe-heat",
        "gust-limit",
    }
    assert all(factor["deduction"] > 0 or factor["ceiling"] is not None for factor in cycling["limiting_factors"])

    comfort = lens_by_id(document, "outdoor_comfort")
    assert comfort["rating"] == "difficult"
    assert {factor["rule"] for factor in comfort["limiting_factors"]} == {
        "comfort-heat",
        "comfort-humid-heat",
        "severe-heat",
        "humid-heat-limit",
    }
    assert lens_by_id(document, "solar_energy")["score"] == 20


def test_commute_lens_uses_only_declared_local_windows() -> None:
    frame = _day_frame()
    local_hours = pd.to_datetime(frame["time"], utc=True).dt.tz_convert(TIMEZONE).dt.hour
    frame.loc[(local_hours >= 11) & (local_hours < 14), "precipitation"] = 4.0

    document = _evaluate(frame)

    assert lens_by_id(document, "cycling")["rating"] == "difficult"
    commute = lens_by_id(document, "outdoor_commute")
    assert commute["rating"] == "favorable"
    assert commute["score"] == 100
    assert commute["evidence"]["precipitation_total_mm"]["value"] == 0.0
    assert document["commute_windows"] == ["06:00-10:00", "15:00-19:00"]


def test_sparse_required_evidence_withholds_only_affected_lenses() -> None:
    frame = _day_frame()
    frame.loc[8:10, "wind_gusts_10m"] = np.nan

    document = _evaluate(frame)

    cycling = lens_by_id(document, "cycling")
    assert cycling["status"] == "insufficient-evidence"
    assert cycling["score"] is None
    assert cycling["missing_or_sparse_facts"] == ["wind_gust_max_ms"]
    assert cycling["evidence"]["wind_gust_max_ms"]["coverage"] == 0.75
    assert lens_by_id(document, "solar_energy")["status"] == "available"
    assert lens_by_id(document, "outdoor_comfort")["status"] == "available"


def test_solar_lens_never_guesses_without_normalized_energy_evidence() -> None:
    document = evaluate_activity_lenses(_day_frame(), TIMEZONE)

    solar = lens_by_id(document, "solar_energy")
    assert solar["status"] == "insufficient-evidence"
    assert solar["missing_or_sparse_facts"] == ["seasonal_radiation_pct"]
    assert solar["score"] is None


def test_dst_day_uses_its_real_local_hour_count() -> None:
    document = _evaluate(_day_frame("2026-10-25"))

    assert document["date"] == "2026-10-25"
    assert document["evidence_quality"]["expected_hours"] == 25
    assert document["evidence_quality"]["present_hours"] == 25
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


def test_subhourly_rows_do_not_manufacture_coverage() -> None:
    frame = _day_frame()
    frame["time"] = pd.date_range(frame["time"].iloc[0], periods=24, freq="10min")
    document = _evaluate(frame)
    assert document["evidence_quality"]["present_hours"] == 4
    assert len(document["evidence_quality"]["off_grid_timestamps"]) == 20
    assert lens_by_id(document, "cycling")["score"] is None


def test_missing_duplicate_invalid_and_dst_slots_are_explicit() -> None:
    frame = _day_frame("2026-03-29")
    frame.loc[4, "precipitation"] = -1
    frame = pd.concat([frame.iloc[1:], frame.iloc[[2]]], ignore_index=True)
    document = _evaluate(frame)
    quality = document["evidence_quality"]
    assert quality["expected_hours"] == 23
    assert quality["present_hours"] == 21
    assert len(quality["missing_slots"]) == len(quality["duplicate_slots"]) == 1
    assert len(document["input_quality"]["precipitation"]["invalid_slots"]) == 1


@pytest.mark.parametrize("metadata", [{}, {"status": "fallback"}])
def test_unverified_or_fallback_scalar_is_not_evidence(metadata: dict) -> None:
    document = evaluate_activity_lenses(_day_frame(), TIMEZONE, energy={"solar_index": 92, "solar_evidence": metadata})
    solar = lens_by_id(document, "solar_energy")
    assert solar["score"] is None
    assert solar["evidence"]["seasonal_radiation_pct"]["coverage"] == 0


def test_finite_derived_solar_value_inherits_missing_inputs() -> None:
    frame = _day_frame()
    frame["shortwave_radiation"] = np.nan
    solar = lens_by_id(_evaluate(frame), "solar_energy")
    assert solar["score"] is None
    assert solar["evidence"]["seasonal_radiation_pct"]["coverage"] == 0


def test_naive_timestamps_are_not_silently_assumed_utc() -> None:
    frame = _day_frame()
    frame["time"] = frame["time"].dt.tz_localize(None)
    with pytest.raises(ActivityLensError, match="invalid timestamps"):
        evaluate_activity_lenses(frame, TIMEZONE)


def test_joint_coverage_cannot_be_replaced_by_individual_column_coverage() -> None:
    frame = _day_frame()
    frame.loc[8, "temperature_2m"] = np.nan
    frame.loc[9, "precipitation"] = np.nan
    cycling = lens_by_id(_evaluate(frame), "cycling")
    assert cycling["score"] is None
    assert cycling["missing_or_sparse_facts"] == ["joint_hourly_inputs"]
    assert cycling["valid_hours"] == 10


def test_missing_slot_breaks_favorable_run_and_cannot_improve_score() -> None:
    frame = _day_frame()
    cycling = lens_by_id(_evaluate(frame.drop(index=13)), "cycling")
    assert cycling["status"] == "available"
    assert cycling["score"] < 100
    assert cycling["hour_counts"]["unknown"] == 1
    assert len(cycling["favorable_windows"]) == 2
    assert sum(run["hours"] for run in cycling["favorable_windows"]) == 11


def test_pv_and_seasonal_reference_withhold_independently() -> None:
    frame = _day_frame()
    frame["direct_radiation"] = frame["shortwave_radiation"] * 0.7
    frame["diffuse_radiation"] = frame["shortwave_radiation"] * 0.3
    physical = {"pv_yield_kwh_per_kwp": 5.1, "pv_evidence": {"status": "derived"}}
    document = evaluate_activity_lenses(frame, TIMEZONE, physical_energy=physical)
    solar = lens_by_id(document, "solar_energy")
    assert solar["score"] is None
    assert solar["pv_estimate"]["status"] == "available"
    frame.loc[13, "direct_radiation"] = np.nan
    solar = lens_by_id(evaluate_activity_lenses(frame, TIMEZONE, physical_energy=physical, solar_reference=_reference(frame)), "solar_energy")
    assert solar["status"] == "available"
    assert solar["pv_estimate"]["status"] == "insufficient-evidence"
    assert solar["pv_estimate"]["value"] is None


def test_partial_daily_radiation_is_not_a_full_day_solar_total() -> None:
    frame = _day_frame()
    frame.loc[13, "shortwave_radiation"] = np.nan
    solar = lens_by_id(_evaluate(frame), "solar_energy")
    assert solar["score"] is None
    assert 0.9 < solar["evidence"]["seasonal_radiation_pct"]["coverage"] < 1


def test_a_missing_journey_withholds_overall_but_preserves_the_other() -> None:
    frame = _day_frame().drop(index=7)
    commute = lens_by_id(_evaluate(frame), "outdoor_commute")
    assert commute["score"] is None
    assert commute["journeys"][0]["status"] == "insufficient-evidence"
    assert commute["journeys"][1]["score"] == 100


def test_invalid_inputs_are_excluded_and_baseline_json_remains_strict() -> None:
    frame = _day_frame()
    frame.loc[8:10, "relative_humidity_2m"] = float("inf")
    reference = _reference(frame, mean=float("nan"))
    document = evaluate_activity_lenses(frame, TIMEZONE, solar_reference=reference)
    assert lens_by_id(document, "outdoor_comfort")["score"] is None
    assert lens_by_id(document, "cycling")["score"] is not None
    assert lens_by_id(document, "solar_energy")["score"] is None
    assert len(document["input_quality"]["relative_humidity_2m"]["invalid_slots"]) == 3
    assert json.loads(activity_lens_json_bytes(document))["solar_reference"]["samples"][0]["radiation_wh_m2"] is None


def test_leap_day_reference_preserves_leap_and_nonleap_calendar_matching() -> None:
    from atlas.climatology import solar_reference_evidence
    from datetime import date

    dates = [date(year, 2, 29 if year % 4 == 0 else 28) for year in range(1991, 2021)]
    archive = pd.DataFrame({"date": dates, "shortwave_radiation_sum": 12.0})
    reference = solar_reference_evidence(archive, date(2028, 2, 29), 1991, 2020, 24)
    solar = lens_by_id(evaluate_activity_lenses(_day_frame("2028-02-29"), TIMEZONE, solar_reference=reference), "solar_energy")
    assert solar["status"] == "available"


def test_fallback_reference_samples_do_not_count_as_valid_years() -> None:
    frame = _day_frame()
    reference = _reference(frame)
    for sample in reference["samples"][:7]:
        sample["status"] = "fallback"
    solar = lens_by_id(evaluate_activity_lenses(frame, TIMEZONE, solar_reference=reference), "solar_energy")
    assert solar["score"] is None


def test_hourly_severity_boundaries_are_monotonic() -> None:
    from atlas.activity_lenses import LENS_SPECS, _evaluate_lens, _weather_facts

    for column, values in (
        ("temperature_2m", [20, 28, 30, 32, 35, 40]),
        ("temperature_2m", [20, 5, 0, -5, -10, -15, -20]),
        ("precipitation", [0, 0.1, 0.5, 2, 5, 10]),
        ("wind_gusts_10m", [5, 8, 12, 14, 18, 20, 24, 30]),
    ):
        for spec in LENS_SPECS:
            if spec.id == "solar_energy":
                continue
            scores = []
            for value in values:
                frame = _day_frame().iloc[[12]].copy()
                frame[column] = value
                scores.append(_evaluate_lens(spec, _weather_facts(frame, 1))["score"])
            assert scores == sorted(scores, reverse=True), (spec.id, column, scores)
