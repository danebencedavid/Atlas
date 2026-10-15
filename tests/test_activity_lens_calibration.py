"""Deliberate scenario evaluation; run directly for a compact review table."""
from __future__ import annotations

import json
import hashlib
import sys
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

from atlas.activity_lenses import evaluate_activity_lenses, lens_by_id
from test_activity_lenses import TIMEZONE, _day_frame, _reference


def scenarios() -> dict[str, pd.DataFrame]:
    frames = {}
    for name, temperature, humidity, wind, gust in (
        ("mild_dry", 20, 50, 3, 5),
        ("mild_winter", 6, 70, 3, 5),
        ("freezing", -2, 70, 3, 5),
        ("severe_cold", -20, 70, 3, 5),
        ("cold_windy", -8, 70, 12, 18),
        ("cold_calm_dry", -8, 70, 1, 2),
        ("comfortable_warm", 26, 45, 3, 5),
        ("hot", 32, 40, 3, 5),
        ("severe_heat", 40, 40, 3, 5),
        ("hot_humid", 32, 75, 3, 5),
        ("hot_dry", 36, 30, 3, 5),
        ("breezy", 20, 50, 5, 8),
        ("persistent_strong_wind", 20, 50, 12, 18),
        ("extreme_gusts", 20, 50, 12, 30),
    ):
        frame = _day_frame()
        frame["temperature_2m"] = temperature
        frame["relative_humidity_2m"] = humidity
        frame["wind_speed_10m"] = wind
        frame["wind_gusts_10m"] = gust
        frames[name] = frame
    for name in (
        "overnight_cold", "warm_morning_hot_afternoon", "overnight_rain", "brief_shower",
        "persistent_light_rain", "heavy_rain", "dry_middle_window", "one_gust_spike",
        "repeated_gusts", "cold_wet_windy", "wet_morning_dry_evening", "dry_morning_wet_evening",
    ):
        frame = _day_frame()
        hour = frame["time"].dt.tz_convert(TIMEZONE).dt.hour
        if name == "overnight_cold":
            frame.loc[hour < 8, "temperature_2m"] = -10
        elif name == "warm_morning_hot_afternoon":
            frame["temperature_2m"] = 25
            frame.loc[(hour >= 12) & (hour < 19), "temperature_2m"] = 38
        elif name == "overnight_rain":
            frame.loc[hour < 6, "precipitation"] = 3
        elif name == "brief_shower":
            frame.loc[hour == 13, "precipitation"] = 1
        elif name == "persistent_light_rain":
            frame["precipitation"] = 0.2
        elif name == "heavy_rain":
            frame["precipitation"] = 6
        elif name == "dry_middle_window":
            frame.loc[(hour < 12) | (hour >= 16), "precipitation"] = 2
        elif name == "one_gust_spike":
            frame.loc[hour == 13, "wind_gusts_10m"] = 22
        elif name == "repeated_gusts":
            frame.loc[(hour >= 13) & (hour < 17), "wind_gusts_10m"] = 22
        elif name == "cold_wet_windy":
            frame["temperature_2m"] = -2
            frame["precipitation"] = 1
            frame["wind_speed_10m"] = 8
            frame["wind_gusts_10m"] = 14
        elif name == "wet_morning_dry_evening":
            frame.loc[(hour >= 6) & (hour < 10), "precipitation"] = 6
        elif name == "dry_morning_wet_evening":
            frame.loc[(hour >= 15) & (hour < 19), "precipitation"] = 6
        frames[name] = frame
    return frames


@lru_cache(maxsize=1)
def evaluated() -> dict[str, dict]:
    return {name: evaluate_activity_lenses(frame, TIMEZONE, solar_reference=_reference(frame))
            for name, frame in scenarios().items()}


def test_extremes_cannot_be_reassuring_without_an_unrelated_penalty() -> None:
    for name in ("severe_cold", "severe_heat", "hot_dry"):
        for lens in evaluated()[name]["lenses"]:
            if lens["id"] != "solar_energy":
                assert lens["rating"] == "difficult", (name, lens["id"])
    for lens_id in ("cycling", "walking", "gardening", "outdoor_commute"):
        assert lens_by_id(evaluated()["extreme_gusts"], lens_id)["rating"] == "difficult"


def test_duration_and_relevant_hours_change_the_result() -> None:
    score = lambda name, key="cycling": lens_by_id(evaluated()[name], key)["score"]
    assert score("mild_dry") == score("overnight_rain") == score("overnight_cold")
    assert score("mild_dry") > score("one_gust_spike") > score("repeated_gusts") > score("extreme_gusts")
    assert score("brief_shower") > score("persistent_light_rain") > score("heavy_rain")
    assert score("cold_calm_dry") >= score("cold_windy")
    assert score("comfortable_warm", "outdoor_comfort") > score("hot", "outdoor_comfort") > score("hot_humid", "outdoor_comfort")
    assert score("persistent_light_rain", "gardening") > score("persistent_light_rain", "walking")
    dry = lens_by_id(evaluated()["dry_middle_window"], "cycling")
    assert dry["rating"] == "difficult"
    assert any(window["hours"] == 4 for window in dry["favorable_windows"])
    assert lens_by_id(evaluated()["overnight_rain"], "cycling")["daily_context"]["precipitation_total_mm"]["value"] > 0


def test_commute_preserves_journey_asymmetry() -> None:
    for name, worse in (("wet_morning_dry_evening", 0), ("dry_morning_wet_evening", 1), ("warm_morning_hot_afternoon", 1)):
        commute = lens_by_id(evaluated()[name], "outdoor_commute")
        assert commute["journeys"][worse]["rating"] == "difficult"
        assert commute["journeys"][1 - worse]["rating"] == "favorable"
        assert commute["score"] == commute["journeys"][worse]["score"]


def test_every_scenario_has_auditable_hours_rules_and_limits() -> None:
    for name, document in evaluated().items():
        for lens in document["lenses"]:
            assert lens["status"] == "available", (name, lens["id"])
            for window in lens.get("journeys", [lens]):
                if "hour_counts" not in window:
                    continue
                assert sum(window["hour_counts"].values()) == window["expected_hours"]
                assert window["score"] <= window["severity_ceiling"]
                assert sum(run["hours"] for run in window["favorable_windows"]) == window["hour_counts"]["favorable"]
                for hour in window["hourly_results"]:
                    for rule in hour["rules"]:
                        assert any(factor["rule"] == rule["rule"] and factor["condition"] == rule["condition"] for factor in window["limiting_factors"])
                    assert hour["score"] <= hour["severity_ceiling"]
                for factor in window["limiting_factors"]:
                    assert factor["hours"] == sum(any(rule["rule"] == factor["rule"] and rule["condition"] == factor["condition"] for rule in hour["rules"]) for hour in window["hourly_results"])


def compare_saved_archive() -> dict:
    """Read cached evidence only; never rewrite a saved result or fetch weather."""
    from atlas.climatology import _payload_frame, solar_reference_evidence
    from atlas.config import load_config
    from atlas.energy import compute_physical_energy

    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "configs/atlas.yml")
    climate = pd.concat([_payload_frame(json.loads((root / f"data/raw/open_meteo_era5_daily_{year}.json").read_text()))
                         for year in range(config.climatology.standard_start_year, config.climatology.standard_end_year + 1)], ignore_index=True)
    paths = sorted((root / "reports/daily").glob("*/data/activity_lenses.json"))
    hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    rows = []
    for path in paths:
        old = json.loads(path.read_text())
        frame = pd.read_csv(path.parent / "daily_hourly.csv")
        day = date.fromisoformat(old["date"])
        physical = compute_physical_energy(config, frame)
        new = evaluate_activity_lenses(frame, TIMEZONE,
            physical_energy={"pv_yield_kwh_per_kwp": physical.pv_yield_kwh_per_kwp, "pv_evidence": physical.pv_evidence},
            solar_reference=solar_reference_evidence(climate, day, config.climatology.standard_start_year,
                                                      config.climatology.standard_end_year, config.climatology.minimum_standard_years),
            source={"provider": "Open-Meteo", "product": "saved historical weather", "resolution": "hourly"})
        rows.append({"date": old["date"], "old": {lens["id"]: lens["score"] for lens in old["lenses"]},
                     "new": {lens["id"]: lens["score"] for lens in new["lenses"]},
                     "radiation_pct": lens_by_id(new, "solar_energy")["evidence"]["seasonal_radiation_pct"]["value"],
                     "comfort_facts": {key: fact["value"] for key, fact in lens_by_id(new, "outdoor_comfort")["evidence"].items()},
                     "json_bytes": len(json.dumps(new).encode()),
                     "old_sha256": hashes[path]})
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in hashes.items())
    keys = list(rows[0]["old"])
    return {"days": len(rows), "first": rows[0]["date"], "last": rows[-1]["date"], "archive_unchanged": True,
            "distributions": {key: {version: dict(Counter(str(row[version][key]) for row in rows)) for version in ("old", "new")} for key in keys},
            "rows": rows}


if __name__ == "__main__":
    if "--archive" in sys.argv:
        print(json.dumps(compare_saved_archive(), indent=2))
        sys.exit(0)
    test_extremes_cannot_be_reassuring_without_an_unrelated_penalty()
    test_duration_and_relevant_hours_change_the_result()
    test_commute_preserves_journey_asymmetry()
    test_every_scenario_has_auditable_hours_rules_and_limits()
    print(json.dumps({name: {lens["id"]: lens["score"] for lens in document["lenses"]} for name, document in evaluated().items()}, indent=2))
