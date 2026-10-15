from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from atlas.serialization import json_ready


ACTIVITY_LENS_SCHEMA = "atlas.activity-lenses/1"
ACTIVITY_LENS_METHODOLOGY = "atlas.activity-lenses/2.0"
MINIMUM_EVIDENCE_COVERAGE = 0.9
DISCLAIMER = (
    "These lenses describe completed historical weather conditions using transparent Atlas "
    "convenience heuristics. They are not forecasts, warnings, medical guidance, "
    "or personal safety advice."
)


class ActivityLensError(ValueError):
    """Raised when activity evidence cannot be interpreted safely."""


@dataclass(frozen=True)
class ActivityFact:
    value: float | None
    unit: str
    coverage: float
    sources: tuple[str, ...]
    kind: str = "derived"
    reason: str | None = None


@dataclass(frozen=True)
class PenaltyBand:
    lower: float | None
    upper: float | None
    deduction: int
    severity: str
    condition: str
    explanation: str
    ceiling: int | None = None

    def matches(self, value: float) -> bool:
        return (self.lower is None or value >= self.lower) and (
            self.upper is None or value < self.upper
        )


@dataclass(frozen=True)
class PenaltyRule:
    id: str
    fact: str
    bands: tuple[PenaltyBand, ...]


@dataclass(frozen=True)
class LensSpec:
    id: str
    label: str
    scope: str
    required_facts: tuple[str, ...]
    observed_facts: tuple[str, ...]
    rules: tuple[PenaltyRule, ...]
    severity_rules: tuple[PenaltyRule, ...] = ()


def _band(
    *,
    lower: float | None = None,
    upper: float | None = None,
    deduction: int,
    severity: str,
    condition: str,
    explanation: str,
    ceiling: int | None = None,
) -> PenaltyBand:
    return PenaltyBand(
        lower=lower,
        upper=upper,
        deduction=deduction,
        severity=severity,
        condition=condition,
        explanation=explanation,
        ceiling=ceiling,
    )


RAIN_BANDS = (
    _band(
        lower=10.0,
        deduction=35,
        severity="major",
        condition=">= 10 mm",
        explanation="Substantial accumulated precipitation made outdoor conditions wet.",
    ),
    _band(
        lower=2.0,
        upper=10.0,
        deduction=20,
        severity="moderate",
        condition="2-10 mm",
        explanation="Measurable accumulated precipitation reduced convenience.",
    ),
    _band(
        lower=0.2,
        upper=2.0,
        deduction=8,
        severity="minor",
        condition="0.2-2 mm",
        explanation="Some precipitation was recorded.",
    ),
)

WET_HOUR_BANDS = (
    _band(
        lower=6.0,
        deduction=20,
        severity="major",
        condition=">= 6 wet hours",
        explanation="Wet conditions persisted through a substantial part of the day.",
    ),
    _band(
        lower=2.0,
        upper=6.0,
        deduction=10,
        severity="moderate",
        condition="2-6 wet hours",
        explanation="Several hours recorded precipitation.",
    ),
    _band(
        lower=1.0,
        upper=2.0,
        deduction=5,
        severity="minor",
        condition="1 wet hour",
        explanation="One wet hour was recorded.",
    ),
)


LENS_SPECS = (
    LensSpec(
        id="cycling",
        label="Cycling conditions",
        scope="all-day",
        required_facts=(
            "precipitation_total_mm",
            "wet_hours",
            "wind_gust_max_ms",
            "temperature_min_c",
            "temperature_max_c",
        ),
        observed_facts=("wind_speed_mean_ms", "sunshine_hours"),
        rules=(
            PenaltyRule("cycling-rain", "precipitation_total_mm", RAIN_BANDS),
            PenaltyRule("cycling-wet-duration", "wet_hours", WET_HOUR_BANDS),
            PenaltyRule(
                "cycling-gusts",
                "wind_gust_max_ms",
                (
                    _band(
                        lower=18.0,
                        deduction=40,
                        severity="major",
                        condition=">= 18 m/s",
                        explanation="Strong hourly gusts substantially reduced cycling convenience.",
                    ),
                    _band(
                        lower=12.0,
                        upper=18.0,
                        deduction=24,
                        severity="moderate",
                        condition="12-18 m/s",
                        explanation="Hourly gusts made cycling more demanding.",
                    ),
                    _band(
                        lower=8.0,
                        upper=12.0,
                        deduction=10,
                        severity="minor",
                        condition="8-12 m/s",
                        explanation="Noticeable gusts reduced this hour's convenience.",
                    ),
                ),
            ),
            PenaltyRule(
                "cycling-heat",
                "temperature_max_c",
                (
                    _band(
                        lower=35.0,
                        deduction=30,
                        severity="major",
                        condition=">= 35 C",
                        explanation="Very high temperature reduced outdoor exertion comfort.",
                    ),
                    _band(
                        lower=30.0,
                        upper=35.0,
                        deduction=15,
                        severity="moderate",
                        condition="30-35 C",
                        explanation="High temperature reduced outdoor exertion comfort.",
                    ),
                ),
            ),
            PenaltyRule(
                "cycling-cold",
                "temperature_min_c",
                (
                    _band(
                        upper=0.0,
                        deduction=25,
                        severity="major",
                        condition="< 0 C",
                        explanation="Freezing temperature reduced cycling comfort.",
                    ),
                    _band(
                        lower=0.0,
                        upper=5.0,
                        deduction=12,
                        severity="moderate",
                        condition="0-5 C",
                        explanation="Low temperature reduced cycling comfort.",
                    ),
                ),
            ),
        ),
    ),
    LensSpec(
        id="walking",
        label="Walking conditions",
        scope="all-day",
        required_facts=(
            "precipitation_total_mm",
            "wet_hours",
            "wind_gust_max_ms",
            "temperature_min_c",
            "temperature_max_c",
        ),
        observed_facts=("sunshine_hours",),
        rules=(
            PenaltyRule("walking-rain", "precipitation_total_mm", RAIN_BANDS),
            PenaltyRule("walking-wet-duration", "wet_hours", WET_HOUR_BANDS),
            PenaltyRule(
                "walking-gusts",
                "wind_gust_max_ms",
                (
                    _band(
                        lower=20.0,
                        deduction=30,
                        severity="major",
                        condition=">= 20 m/s",
                        explanation="Very strong gusts reduced walking comfort.",
                    ),
                    _band(
                        lower=14.0,
                        upper=20.0,
                        deduction=15,
                        severity="moderate",
                        condition="14-20 m/s",
                        explanation="Strong gusts reduced walking comfort.",
                    ),
                ),
            ),
            PenaltyRule(
                "walking-heat",
                "temperature_max_c",
                (
                    _band(
                        lower=35.0,
                        deduction=30,
                        severity="major",
                        condition=">= 35 C",
                        explanation="Very high temperature reduced walking comfort.",
                    ),
                    _band(
                        lower=31.0,
                        upper=35.0,
                        deduction=15,
                        severity="moderate",
                        condition="31-35 C",
                        explanation="High temperature reduced walking comfort.",
                    ),
                ),
            ),
            PenaltyRule(
                "walking-cold",
                "temperature_min_c",
                (
                    _band(
                        upper=-5.0,
                        deduction=25,
                        severity="major",
                        condition="< -5 C",
                        explanation="Very low temperature reduced walking comfort.",
                    ),
                    _band(
                        lower=-5.0,
                        upper=2.0,
                        deduction=10,
                        severity="minor",
                        condition="-5 to 2 C",
                        explanation="Low temperature reduced walking comfort.",
                    ),
                ),
            ),
        ),
    ),
    LensSpec(
        id="outdoor_commute",
        label="Outdoor commute conditions",
        scope="commute-hours",
        required_facts=(
            "precipitation_total_mm",
            "wet_hours",
            "wind_gust_max_ms",
            "temperature_min_c",
            "temperature_max_c",
        ),
        observed_facts=("wind_speed_mean_ms",),
        rules=(
            PenaltyRule("commute-rain", "precipitation_total_mm", RAIN_BANDS),
            PenaltyRule("commute-wet-duration", "wet_hours", WET_HOUR_BANDS),
            PenaltyRule(
                "commute-gusts",
                "wind_gust_max_ms",
                (
                    _band(
                        lower=16.0,
                        deduction=30,
                        severity="major",
                        condition=">= 16 m/s",
                        explanation="Strong gusts affected the morning or afternoon commute window.",
                    ),
                    _band(
                        lower=10.0,
                        upper=16.0,
                        deduction=14,
                        severity="moderate",
                        condition="10-16 m/s",
                        explanation="Noticeable gusts affected a commute window.",
                    ),
                ),
            ),
            PenaltyRule(
                "commute-heat",
                "temperature_max_c",
                (
                    _band(
                        lower=32.0,
                        deduction=20,
                        severity="moderate",
                        condition=">= 32 C",
                        explanation="A commute window was very warm.",
                    ),
                ),
            ),
            PenaltyRule(
                "commute-cold",
                "temperature_min_c",
                (
                    _band(
                        upper=0.0,
                        deduction=18,
                        severity="moderate",
                        condition="< 0 C",
                        explanation="A commute window was below freezing.",
                    ),
                ),
            ),
        ),
    ),
    LensSpec(
        id="gardening",
        label="Hands-on gardening conditions",
        scope="all-day",
        required_facts=(
            "precipitation_total_mm",
            "wet_hours",
            "wind_gust_max_ms",
            "temperature_min_c",
            "temperature_max_c",
        ),
        observed_facts=("evapotranspiration_total_mm", "sunshine_hours"),
        rules=(
            PenaltyRule("gardening-rain", "precipitation_total_mm", RAIN_BANDS),
            PenaltyRule("gardening-wet-duration", "wet_hours", WET_HOUR_BANDS),
            PenaltyRule(
                "gardening-gusts",
                "wind_gust_max_ms",
                (
                    _band(
                        lower=16.0,
                        deduction=30,
                        severity="major",
                        condition=">= 16 m/s",
                        explanation="Strong gusts made hands-on garden work difficult.",
                    ),
                    _band(
                        lower=10.0,
                        upper=16.0,
                        deduction=15,
                        severity="moderate",
                        condition="10-16 m/s",
                        explanation="Gusty conditions reduced gardening convenience.",
                    ),
                ),
            ),
            PenaltyRule(
                "gardening-heat",
                "temperature_max_c",
                (
                    _band(
                        lower=33.0,
                        deduction=25,
                        severity="major",
                        condition=">= 33 C",
                        explanation="Very warm conditions reduced gardening comfort.",
                    ),
                    _band(
                        lower=29.0,
                        upper=33.0,
                        deduction=12,
                        severity="moderate",
                        condition="29-33 C",
                        explanation="Warm conditions reduced gardening comfort.",
                    ),
                ),
            ),
            PenaltyRule(
                "gardening-frost",
                "temperature_min_c",
                (
                    _band(
                        upper=0.0,
                        deduction=25,
                        severity="major",
                        condition="< 0 C",
                        explanation="Freezing temperature constrained garden work and plant handling.",
                    ),
                ),
            ),
        ),
    ),
    LensSpec(
        id="solar_energy",
        label="Solar-energy conditions",
        scope="all-day",
        required_facts=("solar_index",),
        observed_facts=(
            "pv_yield_kwh_per_kwp",
            "cloud_cover_mean_pct",
            "shortwave_total_wh_m2",
        ),
        rules=(
            PenaltyRule(
                "solar-index",
                "solar_index",
                (
                    _band(
                        upper=30.0,
                        deduction=55,
                        severity="major",
                        condition="< 30",
                        explanation="Weather-normalized solar potential was low.",
                    ),
                    _band(
                        lower=30.0,
                        upper=60.0,
                        deduction=30,
                        severity="moderate",
                        condition="30-60",
                        explanation="Weather-normalized solar potential was below typical levels.",
                    ),
                    _band(
                        lower=60.0,
                        upper=80.0,
                        deduction=12,
                        severity="minor",
                        condition="60-80",
                        explanation="Weather-normalized solar potential was somewhat reduced.",
                    ),
                ),
            ),
        ),
    ),
    LensSpec(
        id="outdoor_comfort",
        label="Outdoor temperature comfort",
        scope="all-day",
        required_facts=(
            "temperature_min_c",
            "temperature_max_c",
            "hot_humid_hours",
            "cold_hours",
        ),
        observed_facts=("relative_humidity_mean_pct", "sunshine_hours"),
        rules=(
            PenaltyRule(
                "comfort-heat",
                "temperature_max_c",
                (
                    _band(
                        lower=35.0,
                        deduction=45,
                        severity="major",
                        condition=">= 35 C",
                        explanation="Very high temperature reduced this hour's comfort.",
                    ),
                    _band(
                        lower=30.0,
                        upper=35.0,
                        deduction=25,
                        severity="moderate",
                        condition="30-35 C",
                        explanation="High temperature reduced this hour's comfort.",
                    ),
                ),
            ),
            PenaltyRule(
                "comfort-humid-heat",
                "hot_humid_hours",
                (
                    _band(
                        lower=6.0,
                        deduction=25,
                        severity="major",
                        condition=">= 6 hours at >= 28 C and >= 60% RH",
                        explanation="Warm and humid conditions persisted for several hours.",
                    ),
                    _band(
                        lower=2.0,
                        upper=6.0,
                        deduction=12,
                        severity="moderate",
                        condition="2-6 hours at >= 28 C and >= 60% RH",
                        explanation="Warm and humid conditions occurred for part of the day.",
                    ),
                ),
            ),
            PenaltyRule(
                "comfort-cold",
                "cold_hours",
                (
                    _band(
                        lower=8.0,
                        deduction=30,
                        severity="major",
                        condition=">= 8 hours below 5 C",
                        explanation="Low temperatures persisted through much of the day.",
                    ),
                    _band(
                        lower=2.0,
                        upper=8.0,
                        deduction=15,
                        severity="moderate",
                        condition="2-8 hours below 5 C",
                        explanation="Low temperatures occurred for part of the day.",
                    ),
                ),
            ),
        ),
    ),
)


ACTIVITY_WINDOWS = {
    "cycling": (("daytime", 8, 20),),
    "walking": (("daytime", 8, 20),),
    "gardening": (("daytime", 8, 18),),
    "outdoor_comfort": (("daytime", 8, 20),),
    "outdoor_commute": (("morning", 6, 10), ("evening", 15, 19)),
}


def _ceiling_band(lower: float | None, upper: float | None, ceiling: int, condition: str) -> PenaltyBand:
    return _band(lower=lower, upper=upper, deduction=0, severity="extreme" if ceiling == 29 else "major" if ceiling == 54 else "moderate",
                 ceiling=ceiling, condition=condition, explanation=f"This condition limits the affected hour to {ceiling}/100.")


def _hourly_spec(spec: LensSpec) -> LensSpec:
    """Reuse existing temperature/gust rules; duration is represented by hourly aggregation."""
    if spec.id == "solar_energy":
        return replace(spec, label="Solar conditions relative to season", required_facts=("seasonal_radiation_pct",), rules=())
    rules = tuple(rule for rule in spec.rules if rule.fact not in (
        "precipitation_total_mm", "wet_hours", "cold_hours", "hot_humid_hours",
    ))
    ceilings = [
        PenaltyRule("severe-cold", "temperature_min_c", (
            _ceiling_band(None, -15, 29, "< -15 C"),
            _ceiling_band(-15, -5, 54, "-15 to < -5 C"),
            _ceiling_band(-5, 0, 79, "-5 to < 0 C"),
        )),
        PenaltyRule("severe-heat", "temperature_max_c", (
            _ceiling_band(35, None, 29, ">= 35 C"),
            _ceiling_band(30, 35, 79, "30 to < 35 C"),
        )),
    ]
    if spec.id == "outdoor_comfort":
        rules += (
            PenaltyRule("comfort-cold", "temperature_min_c", (
                _band(upper=5, deduction=15, severity="moderate", condition="< 5 C", explanation="Low temperature reduced this hour's comfort."),
            )),
            PenaltyRule("comfort-humid-heat", "hot_humid_hours", (
                _band(lower=1, deduction=12, severity="moderate", condition=">= 28 C and >= 60% RH", explanation="Warm and humid conditions reduced this hour's comfort."),
            )),
        )
        ceilings.append(PenaltyRule("humid-heat-limit", "humid_heat_temperature_c", (
            _ceiling_band(32, None, 54, ">= 32 C and >= 60% RH"),
            _ceiling_band(28, 32, 79, "28 to < 32 C and >= 60% RH"),
        )))
    else:
        light_deduction = 10 if spec.id == "gardening" else 20
        rules += (
            PenaltyRule(f"{spec.id}-rain", "precipitation_total_mm", (
                _band(lower=5, deduction=65, ceiling=29, severity="extreme", condition=">= 5 mm/hour", explanation="Heavy hourly rain strongly constrained activity."),
                _band(lower=2, upper=5, deduction=45, ceiling=54, severity="major", condition="2 to < 5 mm/hour", explanation="Hourly rain constrained activity."),
                _band(lower=0.5, upper=2, deduction=30, ceiling=79, severity="moderate", condition="0.5 to < 2 mm/hour", explanation="Rain reduced this hour's convenience."),
                _band(lower=0.1, upper=0.5, deduction=light_deduction, ceiling=None if spec.id == "gardening" else 79,
                      severity="minor", condition="0.1 to < 0.5 mm/hour", explanation="Light rain affected this hour; gardening tolerates light rain without assuming workable soil." if spec.id == "gardening" else "Light rain reduced this hour's convenience."),
            )),
        )
        wind_thresholds = {"cycling": (6, 10, 15), "walking": (10, 15, 20), "outdoor_commute": (8, 12, 17), "gardening": (8, 12, 17)}[spec.id]
        low, high, extreme = wind_thresholds
        rules += (PenaltyRule(f"{spec.id}-sustained-wind", "wind_speed_mean_ms", (
            _band(lower=extreme, deduction=40, ceiling=29, severity="extreme", condition=f">= {extreme} m/s", explanation="Very strong sustained wind constrained this hour."),
            _band(lower=high, upper=extreme, deduction=25, ceiling=54, severity="major", condition=f"{high} to < {extreme} m/s", explanation="Strong sustained wind constrained this hour."),
            _band(lower=low, upper=high, deduction=10, ceiling=79, severity="moderate", condition=f"{low} to < {high} m/s", explanation="Persistent wind reduced this hour's convenience."),
        )),)
        gust_high, gust_extreme = {"cycling": (12, 18), "walking": (14, 24), "outdoor_commute": (14, 20), "gardening": (14, 20)}[spec.id]
        ceilings.append(PenaltyRule("gust-limit", "wind_gust_max_ms", (
            _ceiling_band(gust_extreme, None, 29, f">= {gust_extreme} m/s"),
            _ceiling_band(gust_high, gust_extreme, 54, f"{gust_high} to < {gust_extreme} m/s"),
        )))
    required = tuple(dict.fromkeys((*spec.required_facts, *(rule.fact for rule in rules + tuple(ceilings)))))
    # Duration rules have been replaced by per-hour conditions and persistence counts.
    required = tuple(key for key in required if key not in ("wet_hours", "cold_hours"))
    return replace(spec, scope="activity-hours", required_facts=required, rules=rules, severity_rules=tuple(ceilings))


LENS_SPECS = tuple(_hourly_spec(spec) for spec in LENS_SPECS)


INPUT_BOUNDS = {
    "temperature_2m": (-100, 65),
    "relative_humidity_2m": (0, 100),
    "precipitation": (0, None),
    "wind_speed_10m": (0, None),
    "wind_gusts_10m": (0, None),
    "cloud_cover": (0, 100),
    "shortwave_radiation": (0, None),
    "direct_radiation": (0, None),
    "diffuse_radiation": (0, None),
    "sunshine_duration": (0, 3600),
    "et0_fao_evapotranspiration": (0, None),
}


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(float("nan"), index=frame.index)
    values = pd.to_numeric(frame[column], errors="coerce")
    lower, upper = INPUT_BOUNDS.get(column, (None, None))
    valid = np.isfinite(values) & ~frame[column].map(lambda value: isinstance(value, (bool, np.bool_)))
    if lower is not None:
        valid &= values >= lower
    if upper is not None:
        valid &= values <= upper
    return values.where(valid)


def _coverage(series: pd.Series, expected_hours: int) -> float:
    if expected_hours <= 0:
        return 0.0
    return min(float(series.notna().sum()) / expected_hours, 1.0)


def _fact(
    series: pd.Series,
    expected_hours: int,
    unit: str,
    sources: tuple[str, ...],
    aggregation: str,
) -> ActivityFact:
    coverage = _coverage(series, expected_hours)
    clean = series.dropna()
    if clean.empty:
        value = None
    elif aggregation == "sum":
        value = float(clean.sum())
    elif aggregation == "mean":
        value = float(clean.mean())
    elif aggregation == "min":
        value = float(clean.min())
    elif aggregation == "max":
        value = float(clean.max())
    elif aggregation == "wet-hours":
        value = float((clean >= 0.1).sum())
    elif aggregation == "cold-hours":
        value = float((clean < 5.0).sum())
    else:
        raise ActivityLensError(f"Unsupported activity aggregation: {aggregation}")
    if value is not None and not math.isfinite(value):
        value = None
    return ActivityFact(value, unit, round(coverage, 4), sources)


def _hot_humid_fact(frame: pd.DataFrame, expected_hours: int) -> ActivityFact:
    temperature = _numeric_series(frame, "temperature_2m")
    humidity = _numeric_series(frame, "relative_humidity_2m")
    paired = pd.concat((temperature, humidity), axis=1).dropna()
    coverage = min(float(len(paired)) / expected_hours, 1.0) if expected_hours else 0.0
    value = (
        float(((paired.iloc[:, 0] >= 28.0) & (paired.iloc[:, 1] >= 60.0)).sum())
        if not paired.empty
        else None
    )
    return ActivityFact(
        value,
        "hours",
        round(coverage, 4),
        ("temperature_2m", "relative_humidity_2m"),
    )


def _weather_facts(frame: pd.DataFrame, expected_hours: int) -> dict[str, ActivityFact]:
    temperature = _numeric_series(frame, "temperature_2m")
    precipitation = _numeric_series(frame, "precipitation")
    humidity = _numeric_series(frame, "relative_humidity_2m")
    return {
        "precipitation_total_mm": _fact(
            precipitation, expected_hours, "mm", ("precipitation",), "sum"
        ),
        "wet_hours": _fact(
            precipitation, expected_hours, "hours", ("precipitation",), "wet-hours"
        ),
        "temperature_min_c": _fact(
            temperature, expected_hours, "C", ("temperature_2m",), "min"
        ),
        "temperature_max_c": _fact(
            temperature, expected_hours, "C", ("temperature_2m",), "max"
        ),
        "cold_hours": _fact(
            temperature, expected_hours, "hours", ("temperature_2m",), "cold-hours"
        ),
        "hot_humid_hours": _hot_humid_fact(frame, expected_hours),
        "humid_heat_temperature_c": _fact(
            temperature.where(humidity >= 60, 0).where(temperature.notna() & humidity.notna()),
            expected_hours, "C", ("temperature_2m", "relative_humidity_2m"), "max",
        ),
        "relative_humidity_mean_pct": _fact(
            _numeric_series(frame, "relative_humidity_2m"),
            expected_hours,
            "%",
            ("relative_humidity_2m",),
            "mean",
        ),
        "wind_speed_mean_ms": _fact(
            _numeric_series(frame, "wind_speed_10m"),
            expected_hours,
            "m/s",
            ("wind_speed_10m",),
            "mean",
        ),
        "wind_gust_max_ms": _fact(
            _numeric_series(frame, "wind_gusts_10m"),
            expected_hours,
            "m/s",
            ("wind_gusts_10m",),
            "max",
        ),
        "cloud_cover_mean_pct": _fact(
            _numeric_series(frame, "cloud_cover"),
            expected_hours,
            "%",
            ("cloud_cover",),
            "mean",
        ),
        "shortwave_total_wh_m2": _fact(
            _numeric_series(frame, "shortwave_radiation"),
            expected_hours,
            "Wh/m2",
            ("shortwave_radiation",),
            "sum",
        ),
        "sunshine_hours": _fact(
            _numeric_series(frame, "sunshine_duration") / 3600.0,
            expected_hours,
            "hours",
            ("sunshine_duration",),
            "sum",
        ),
        "evapotranspiration_total_mm": _fact(
            _numeric_series(frame, "et0_fao_evapotranspiration"),
            expected_hours,
            "mm",
            ("et0_fao_evapotranspiration",),
            "sum",
        ),
    }


def _supplemental_fact(
    source: Mapping[str, Any] | None,
    key: str,
    unit: str,
    source_name: str,
    frame: pd.DataFrame,
    dependencies: tuple[str, ...],
    metadata_key: str,
) -> ActivityFact:
    raw = source.get(key) if source is not None else None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        value = None
    else:
        value = float(raw)
        if not math.isfinite(value):
            value = None
    metadata = source.get(metadata_key, {}) if source else {}
    metadata = metadata if isinstance(metadata, Mapping) else {}
    valid = metadata.get("status") == "derived"
    if value is not None and value < 0:
        value = None
    paired = pd.concat([_numeric_series(frame, key) for key in dependencies], axis=1)
    coverage = float(paired.notna().all(axis=1).mean()) if len(frame) else 0.0
    reason = None
    if not valid:
        reason = "Missing dependency validity or fallback upstream calculation."
    elif value is None:
        reason = "Derived value is missing or invalid."
    elif coverage < 1:
        reason = "Full-day PV yield requires every expected model-input slot; no missing hours are filled."
    return ActivityFact(
        value if valid and coverage == 1 else None, unit, coverage if valid and value is not None else 0.0,
        (source_name, *dependencies), "derived" if valid else "fallback" if metadata.get("status") == "fallback" else "unverified", reason,
    )


def _expected_hours(day: date, timezone_name: str) -> int:
    zone = ZoneInfo(timezone_name)
    start = datetime.combine(day, time.min, zone).astimezone(ZoneInfo("UTC"))
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(
        ZoneInfo("UTC")
    )
    return round((end - start).total_seconds() / 3600.0)


def _prepare_frame(frame: pd.DataFrame, timezone_name: str) -> tuple[pd.DataFrame, date]:
    if frame.empty or "time" not in frame:
        raise ActivityLensError("Activity lenses require timestamped hourly evidence")
    prepared = frame.copy()
    try:
        if any(pd.isna(value) or pd.Timestamp(value).tzinfo is None for value in prepared["time"]):
            raise ValueError("Timezone-aware timestamps are required")
        prepared["_time"] = pd.to_datetime(prepared["time"], utc=True, errors="raise")
        prepared["_local_time"] = prepared["_time"].dt.tz_convert(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ActivityLensError("Activity evidence has invalid timestamps or timezone") from exc
    local_days = prepared["_local_time"].dt.date.unique()
    if len(local_days) != 1:
        raise ActivityLensError("Activity lenses require exactly one local calendar day")
    day = local_days[0]
    start = pd.Timestamp(day, tz=timezone_name)
    expected = pd.date_range(start, start + pd.DateOffset(days=1), freq="h", inclusive="left").tz_convert("UTC")
    off_grid = ~prepared["_time"].isin(expected)
    duplicates = prepared["_time"].duplicated(keep=False)
    accepted = prepared[~off_grid & ~duplicates].set_index("_time").reindex(expected)
    quality = {
        "expected_hours": len(expected),
        "present_hours": int((~off_grid & ~duplicates).sum()),
        "missing_slots": [value.isoformat() for value in expected if value not in set(prepared["_time"])],
        "duplicate_slots": sorted(set(prepared.loc[duplicates, "_time"].map(pd.Timestamp.isoformat))),
        "off_grid_timestamps": sorted(prepared.loc[off_grid, "_time"].map(pd.Timestamp.isoformat)),
        "minimum_lens_coverage": MINIMUM_EVIDENCE_COVERAGE,
    }
    quality["coverage"] = quality["present_hours"] / len(expected)
    accepted["_time"] = expected
    accepted["_local_time"] = expected.tz_convert(timezone_name)
    accepted.attrs["temporal_quality"] = quality
    return accepted, day


def _commute_frame(frame: pd.DataFrame) -> pd.DataFrame:
    local_hour = frame["_local_time"].dt.hour
    return frame[((local_hour >= 6) & (local_hour < 10)) | ((local_hour >= 15) & (local_hour < 19))]


def _fact_document(fact: ActivityFact) -> dict[str, Any]:
    return {
        "value": round(fact.value, 3) if fact.value is not None else None,
        "unit": fact.unit,
        "coverage": fact.coverage,
        "sources": list(fact.sources),
        "kind": fact.kind,
        "reason": fact.reason,
    }


def _evaluate_lens(
    spec: LensSpec,
    facts: Mapping[str, ActivityFact],
) -> dict[str, Any]:
    unavailable = [
        key
        for key in spec.required_facts
        if key not in facts
        or facts[key].value is None
        or facts[key].coverage < MINIMUM_EVIDENCE_COVERAGE
    ]
    evidence_keys = tuple(dict.fromkeys((*spec.required_facts, *spec.observed_facts)))
    evidence = {
        key: _fact_document(facts[key])
        for key in evidence_keys
        if key in facts
    }
    if unavailable:
        return {
            "id": spec.id,
            "label": spec.label,
            "scope": spec.scope,
            "status": "insufficient-evidence",
            "rating": None,
            "score": None,
            "summary": " ".join(dict.fromkeys(facts[key].reason for key in unavailable if key in facts and facts[key].reason)) or "Insufficient valid historical weather evidence for this lens.",
            "missing_or_sparse_facts": unavailable,
            "limiting_factors": [],
            "evidence": evidence,
        }

    limiting: list[dict[str, Any]] = []
    for rule in (*spec.rules, *spec.severity_rules):
        fact = facts[rule.fact]
        assert fact.value is not None
        match = next((band for band in rule.bands if band.matches(fact.value)), None)
        if match is None:
            continue
        limiting.append(
            {
                "rule": rule.id,
                "fact": rule.fact,
                "value": round(fact.value, 3),
                "unit": fact.unit,
                "condition": match.condition,
                "deduction": match.deduction,
                "severity": match.severity,
                "explanation": match.explanation,
                "ceiling": match.ceiling,
            }
        )

    ceiling = min((item["ceiling"] for item in limiting if item["ceiling"] is not None), default=100)
    score = min(max(100 - sum(item["deduction"] for item in limiting), 0), ceiling)
    rating = "favorable" if score >= 80 else "mixed" if score >= 55 else "difficult"
    if not limiting:
        summary = "No limiting condition crossed this lens's convenience thresholds."
    else:
        summary = (
            f"{len(limiting)} historical weather condition"
            f"{'s' if len(limiting) != 1 else ''} reduced this lens's rating."
        )
    return {
        "id": spec.id,
        "label": spec.label,
        "scope": spec.scope,
        "status": "available",
        "rating": rating,
        "score": score,
        "severity_ceiling": ceiling,
        "summary": summary,
        "missing_or_sparse_facts": [],
        "limiting_factors": limiting,
        "evidence": evidence,
    }


def _rating(score: int) -> str:
    return "favorable" if score >= 80 else "mixed" if score >= 55 else "difficult"


def _evaluate_window(spec: LensSpec, frame: pd.DataFrame, name: str, start: int, end: int) -> dict[str, Any]:
    selected = frame[(frame["_local_time"].dt.hour >= start) & (frame["_local_time"].dt.hour < end)]
    expected = len(selected)
    facts = _weather_facts(selected, expected)
    result = _evaluate_lens(spec, facts)
    dependencies = tuple(dict.fromkeys(source for key in spec.required_facts for source in facts[key].sources))
    numeric = pd.DataFrame({key: _numeric_series(selected, key) for key in dependencies})
    usable = numeric.notna().all(axis=1)
    coverage = float(usable.mean()) if expected else 0.0
    hours = []
    factors: dict[tuple[str, str], dict] = {}
    for timestamp, row in selected.iterrows():
        if not usable.loc[timestamp]:
            hours.append({"time": timestamp.isoformat(), "score": None, "rating": None, "severity_ceiling": None, "rules": []})
            continue
        hourly = _evaluate_lens(spec, _weather_facts(selected.loc[[timestamp]], 1))
        hours.append({
            "time": timestamp.isoformat(), "score": hourly["score"], "rating": hourly["rating"],
            "severity_ceiling": hourly["severity_ceiling"],
            "rules": [{key: item[key] for key in ("rule", "condition", "deduction", "ceiling")} for item in hourly["limiting_factors"]],
        })
        for item in hourly["limiting_factors"]:
            key = (item["rule"], item["condition"])
            if key not in factors:
                factors[key] = {**item, "hours": 0, "minimum_value": item["value"], "maximum_value": item["value"]}
            factors[key]["hours"] += 1
            factors[key]["minimum_value"] = min(factors[key]["minimum_value"], item["value"])
            factors[key]["maximum_value"] = max(factors[key]["maximum_value"], item["value"])
    counts = {rating: sum(hour["rating"] == rating for hour in hours) for rating in ("favorable", "mixed", "difficult")}
    counts["unknown"] = sum(hour["score"] is None for hour in hours)
    severe_hours = sum(hour["severity_ceiling"] is not None and hour["severity_ceiling"] <= 54 for hour in hours)
    extreme_hours = sum(hour["severity_ceiling"] is not None and hour["severity_ceiling"] <= 29 for hour in hours)
    limits = []
    if expected and severe_hours / expected >= 0.25:
        limits.append({"rule": "persistent-severity", "ceiling": 54, "hours": severe_hours, "explanation": "Severe conditions affected at least 25% of the evaluated hours."})
    if extreme_hours:
        limits.append({"rule": "notable-extreme", "ceiling": 79, "hours": extreme_hours, "explanation": "At least one strongly constrained hour prevents a favorable whole-window rating."})
    runs = []
    for hour in hours:
        if hour["rating"] != "favorable":
            continue
        timestamp = pd.Timestamp(hour["time"])
        if runs and runs[-1]["end"] == timestamp.isoformat():
            runs[-1]["end"] = (timestamp + pd.Timedelta(hours=1)).isoformat()
            runs[-1]["hours"] += 1
        else:
            runs.append({"start": timestamp.isoformat(), "end": (timestamp + pd.Timedelta(hours=1)).isoformat(), "hours": 1})
    result.update({
        "window": name, "local_window": f"{start:02}:00-{end:02}:00", "expected_hours": expected,
        "valid_hours": int(usable.sum()), "coverage": coverage, "hour_counts": counts,
        "favorable_windows": runs, "hourly_results": hours, "limiting_factors": list(factors.values()),
        "rating_limits": limits, "severity_ceiling": min((limit["ceiling"] for limit in limits), default=100),
    })
    if coverage < MINIMUM_EVIDENCE_COVERAGE or result["status"] != "available":
        result.update(status="insufficient-evidence", score=None, rating=None,
                      summary=f"Only {int(usable.sum())}/{expected} evaluated hourly slots have all required inputs.")
        if coverage < MINIMUM_EVIDENCE_COVERAGE and not result["missing_or_sparse_facts"]:
            result["missing_or_sparse_facts"] = ["joint_hourly_inputs"]
        return result
    raw_score = math.floor(sum(hour["score"] or 0 for hour in hours) / expected)
    score = min(raw_score, result["severity_ceiling"])
    result.update(score=score, rating=_rating(score),
                  summary=f"{counts['favorable']}/{expected} favorable hours; {counts['mixed']} mixed, {counts['difficult']} difficult and {counts['unknown']} unknown hours in {start:02}:00-{end:02}:00 local time.")
    result["score_before_window_limits"] = raw_score
    return result


def _evaluate_activity(spec: LensSpec, frame: pd.DataFrame, daily_facts: Mapping[str, ActivityFact]) -> dict[str, Any]:
    windows = [_evaluate_window(spec, frame, *window) for window in ACTIVITY_WINDOWS[spec.id]]
    if len(windows) == 1:
        result = windows[0]
    else:
        available = all(window["status"] == "available" for window in windows)
        result = dict(min(windows, key=lambda window: window["score"] if window["score"] is not None else -1))
        result["summary"] = "Morning and evening are evaluated separately; the overall result uses the less favorable journey."
        result["journeys"] = windows
        result["combination"] = "minimum-of-journeys"
        result["window"] = "commute"
        if not available:
            result.update(status="insufficient-evidence", score=None, rating=None)
    result["daily_context"] = {key: _fact_document(daily_facts[key]) for key in (
        "temperature_min_c", "temperature_max_c", "wind_gust_max_ms", "precipitation_total_mm", "wet_hours",
    )}
    return result


def _seasonal_solar_fact(reference: Mapping[str, Any] | None, frame: pd.DataFrame, day: date) -> ActivityFact:
    radiation = _numeric_series(frame, "shortwave_radiation")
    coverage = float(radiation.notna().mean())
    reason = "A valid same-calendar radiation reference is required."
    baseline = None
    if reference and reference.get("status") == "derived" and reference.get("date") == day.isoformat():
        samples = reference.get("samples", [])
        if not isinstance(samples, list):
            samples = []
        minimum = reference.get("minimum_years")
        dates = [sample.get("date") for sample in samples if isinstance(sample, Mapping)]
        values = [sample.get("radiation_wh_m2") for sample in samples if isinstance(sample, Mapping) and sample.get("status") == "valid"]
        valid_values = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0]
        same_calendar = True
        for value in dates:
            try:
                sample_day = date.fromisoformat(value)
                try:
                    expected_day = day.replace(year=sample_day.year)
                except ValueError:
                    expected_day = day.replace(year=sample_day.year, day=28)
                same_calendar &= sample_day == expected_day and sample_day.year < day.year
            except (TypeError, ValueError):
                same_calendar = False
        if (same_calendar and len(samples) == len(dates)
                and isinstance(minimum, int) and not isinstance(minimum, bool) and minimum > 0
                and len(valid_values) >= minimum and len(dates) == len(set(dates))
                and len(samples) == reference.get("expected_years")):
            baseline = sum(valid_values) / len(valid_values)
    if baseline is None or not math.isfinite(baseline) or baseline <= 0:
        return ActivityFact(None, "% of seasonal normal", 0, ("shortwave_radiation", "solar_reference"), "unverified", reason)
    if coverage < 1:
        return ActivityFact(None, "% of seasonal normal", coverage, ("shortwave_radiation", "solar_reference"), "derived", "Full-day radiation requires every expected hourly input; no missing hours are filled.")
    ratio = float(radiation.sum()) / baseline * 100
    if not math.isfinite(ratio):
        return ActivityFact(None, "% of seasonal normal", 0, ("shortwave_radiation", "solar_reference"), "unverified", "Invalid derived radiation ratio.")
    return ActivityFact(ratio, "% of seasonal normal", coverage,
                        ("shortwave_radiation", "solar_reference"))


def _evaluate_solar(spec: LensSpec, facts: Mapping[str, ActivityFact]) -> dict[str, Any]:
    result = _evaluate_lens(spec, facts)
    if result["status"] == "available":
        ratio = facts["seasonal_radiation_pct"].value
        assert ratio is not None
        score = min(100, max(0, math.floor(ratio)))
        result.update(score=score, rating=_rating(score), summary=f"Daily radiation was {ratio:.1f}% of the same-calendar seasonal normal; this is not an energy yield.")
    pv = facts["pv_yield_kwh_per_kwp"]
    result["pv_estimate"] = {
        **_fact_document(pv), "status": "available" if pv.value is not None and pv.coverage == 1 else "insufficient-evidence",
        "label": "Estimated reference-system PV yield", "requires_climate_baseline": False,
    }
    if result["pv_estimate"]["status"] != "available":
        result["pv_estimate"]["value"] = None
    return result


def activity_lens_methodology() -> dict[str, Any]:
    """Describe the complete scoring method in a serializable, inspectable form."""

    return {
        "version": ACTIVITY_LENS_METHODOLOGY,
        "calibration_status": "provisional transparent heuristics; scenario-tested, not physiological validation",
        "solar_calculation": "100 * complete daily radiation / valid same-calendar mean radiation. Save the uncapped ratio; the displayed score is its floor clipped to 0-100. No cloud penalty. PV yield is separate and requires complete model inputs, not a climate baseline.",
        "base_score": 100,
        "score_floor": 0,
        "calculation": (
            "For each usable activity hour start at 100, subtract one matching band per rule, "
            "floor at zero and apply the smallest severity ceiling. Divide the sum by expected hours "
            "and round down. Unknown hours add no credit. At least 25% severe hours caps the window at 54; "
            "any hour capped at 29 caps the window at 79. Commute uses the worse of two journeys. "
            "Solar uses the separately stated season-relative radiation ratio."
        ),
        "rating_bands": [
            {"rating": "favorable", "condition": "80-100"},
            {"rating": "mixed", "condition": "55-79"},
            {"rating": "difficult", "condition": "0-54"},
        ],
        "minimum_required_fact_coverage": MINIMUM_EVIDENCE_COVERAGE,
        "coverage_policy": (
            "Require at least 90% jointly valid expected slots per activity window; solar and PV daily totals require 100%. "
            "Withhold only affected results; never substitute missing or fallback evidence."
        ),
        "lenses": [
            {
                "id": spec.id,
                "label": spec.label,
                "scope": spec.scope,
                "windows": [f"{start:02}:00-{end:02}:00" for _, start, end in ACTIVITY_WINDOWS.get(spec.id, ())] or ["Full local day"],
                "rules": [
                    {
                        "id": rule.id,
                        "fact": rule.fact,
                        "bands": [
                            {
                                "condition": band.condition,
                                "deduction": band.deduction,
                                "severity": band.severity,
                                "explanation": band.explanation,
                                "ceiling": band.ceiling,
                            }
                            for band in rule.bands
                        ],
                    }
                    for rule in (*spec.rules, *spec.severity_rules)
                ],
            }
            for spec in LENS_SPECS
        ],
    }


def evaluate_activity_lenses(
    hourly: pd.DataFrame,
    timezone_name: str,
    *,
    energy: Mapping[str, Any] | None = None,
    physical_energy: Mapping[str, Any] | None = None,
    source: Mapping[str, Any] | None = None,
    solar_reference: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate completed daily historical weather through transparent activity lenses."""

    prepared, local_day = _prepare_frame(hourly, timezone_name)
    expected = _expected_hours(local_day, timezone_name)
    all_day_facts = _weather_facts(prepared, expected)
    # Legacy communication indices cannot establish baseline validity for a lens.
    all_day_facts["seasonal_radiation_pct"] = _seasonal_solar_fact(solar_reference, prepared, local_day)
    all_day_facts["pv_yield_kwh_per_kwp"] = _supplemental_fact(
        physical_energy,
        "pv_yield_kwh_per_kwp",
        "kWh/kWp",
        "daily_physical_energy.pv_yield_kwh_per_kwp",
        prepared,
        ("shortwave_radiation", "direct_radiation", "diffuse_radiation", "temperature_2m", "wind_speed_10m"),
        "pv_evidence",
    )

    lenses = [_evaluate_solar(spec, all_day_facts) if spec.id == "solar_energy"
              else _evaluate_activity(spec, prepared, all_day_facts) for spec in LENS_SPECS]
    input_quality = {}
    for column in INPUT_BOUNDS:
        values = _numeric_series(prepared, column)
        raw = prepared[column] if column in prepared else pd.Series(np.nan, index=prepared.index)
        input_quality[column] = {
            "valid_slots": int(values.notna().sum()),
            "missing_slots": [t.isoformat() for t in prepared.index[raw.isna()]],
            "invalid_slots": [t.isoformat() for t in prepared.index[raw.notna() & values.isna()]],
            "coverage": float(values.notna().mean()),
            "kind": "source-value",
        }
    return {
        "schema": ACTIVITY_LENS_SCHEMA,
        "methodology_version": ACTIVITY_LENS_METHODOLOGY,
        "scope": "completed-historical-day",
        "date": local_day.isoformat(),
        "timezone": timezone_name,
        "disclaimer": DISCLAIMER,
        "evidence_quality": prepared.attrs["temporal_quality"],
        "input_quality": input_quality,
        "source": dict(source or {"provider": "unspecified", "product": "caller-supplied historical weather"}),
        "solar_reference": json_ready(dict(solar_reference or {})),
        "pv_model": json_ready(physical_energy.get("pv_evidence", {})) if physical_energy else {},
        "hourly_evidence": [
            {"time": timestamp.isoformat(), **{key: (float(value) if pd.notna(value) else None) for key, value in row.items()}}
            for timestamp, row in pd.DataFrame({key: _numeric_series(prepared, key) for key in INPUT_BOUNDS}).iterrows()
        ],
        "commute_windows": ["06:00-10:00", "15:00-19:00"],
        "methodology": activity_lens_methodology(),
        "lenses": lenses,
    }


def activity_lens_json_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize a lens result deterministically for immutable daily evidence."""

    return (
        json.dumps(
            document,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_activity_lens_evidence(
    output_path: str | Path,
    hourly: pd.DataFrame,
    timezone_name: str,
    *,
    energy: Mapping[str, Any] | None = None,
    physical_energy: Mapping[str, Any] | None = None,
    source: Mapping[str, Any] | None = None,
    solar_reference: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate and atomically persist one immutable daily lens document."""

    document = evaluate_activity_lenses(
        hourly,
        timezone_name,
        energy=energy,
        physical_energy=physical_energy,
        source=source,
        solar_reference=solar_reference,
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(activity_lens_json_bytes(document))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return document


def lens_by_id(document: Mapping[str, Any], lens_id: str) -> Mapping[str, Any]:
    """Return one lens from a generated document without hiding a missing id."""

    for lens in document.get("lenses", []):
        if lens.get("id") == lens_id:
            return lens
    raise KeyError(lens_id)


def available_lens_ids() -> tuple[str, ...]:
    return tuple(spec.id for spec in LENS_SPECS)
