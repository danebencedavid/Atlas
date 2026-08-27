from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd


ACTIVITY_LENS_SCHEMA = "atlas.activity-lenses/1"
MINIMUM_EVIDENCE_COVERAGE = 0.9
DISCLAIMER = (
    "These lenses describe completed observed conditions using transparent Atlas "
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


@dataclass(frozen=True)
class PenaltyBand:
    lower: float | None
    upper: float | None
    deduction: int
    severity: str
    condition: str
    explanation: str

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


def _band(
    *,
    lower: float | None = None,
    upper: float | None = None,
    deduction: int,
    severity: str,
    condition: str,
    explanation: str,
) -> PenaltyBand:
    return PenaltyBand(
        lower=lower,
        upper=upper,
        deduction=deduction,
        severity=severity,
        condition=condition,
        explanation=explanation,
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
                        explanation="Strong recorded gusts substantially reduced cycling convenience.",
                    ),
                    _band(
                        lower=12.0,
                        upper=18.0,
                        deduction=24,
                        severity="moderate",
                        condition="12-18 m/s",
                        explanation="Recorded gusts made cycling more demanding.",
                    ),
                    _band(
                        lower=8.0,
                        upper=12.0,
                        deduction=10,
                        severity="minor",
                        condition="8-12 m/s",
                        explanation="Noticeable gusts were recorded.",
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
                        explanation="Very high observed temperature reduced outdoor comfort.",
                    ),
                    _band(
                        lower=30.0,
                        upper=35.0,
                        deduction=25,
                        severity="moderate",
                        condition="30-35 C",
                        explanation="High observed temperature reduced outdoor comfort.",
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


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


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
) -> ActivityFact:
    raw = source.get(key) if source is not None else None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        value = None
    else:
        value = float(raw)
        if not math.isfinite(value):
            value = None
    return ActivityFact(value, unit, 1.0 if value is not None else 0.0, (source_name,))


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
        prepared["_time"] = pd.to_datetime(prepared["time"], utc=True, errors="raise")
        prepared["_local_time"] = prepared["_time"].dt.tz_convert(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ActivityLensError("Activity evidence has invalid timestamps or timezone") from exc
    local_days = prepared["_local_time"].dt.date.unique()
    if len(local_days) != 1:
        raise ActivityLensError("Activity lenses require exactly one local calendar day")
    prepared = prepared.sort_values("_time").drop_duplicates("_time", keep="last")
    return prepared, local_days[0]


def _commute_frame(frame: pd.DataFrame) -> pd.DataFrame:
    local_hour = frame["_local_time"].dt.hour
    return frame[((local_hour >= 6) & (local_hour < 10)) | ((local_hour >= 15) & (local_hour < 19))]


def _fact_document(fact: ActivityFact) -> dict[str, Any]:
    return {
        "value": round(fact.value, 3) if fact.value is not None else None,
        "unit": fact.unit,
        "coverage": fact.coverage,
        "sources": list(fact.sources),
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
            "summary": "Insufficient observed evidence for this lens.",
            "missing_or_sparse_facts": unavailable,
            "limiting_factors": [],
            "evidence": evidence,
        }

    limiting: list[dict[str, Any]] = []
    for rule in spec.rules:
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
            }
        )

    score = max(100 - sum(item["deduction"] for item in limiting), 0)
    rating = "favorable" if score >= 80 else "mixed" if score >= 55 else "difficult"
    if not limiting:
        summary = "No limiting condition crossed this lens's convenience thresholds."
    else:
        summary = (
            f"{len(limiting)} observed condition"
            f"{'s' if len(limiting) != 1 else ''} reduced this lens's rating."
        )
    return {
        "id": spec.id,
        "label": spec.label,
        "scope": spec.scope,
        "status": "available",
        "rating": rating,
        "score": score,
        "summary": summary,
        "missing_or_sparse_facts": [],
        "limiting_factors": limiting,
        "evidence": evidence,
    }


def evaluate_activity_lenses(
    hourly: pd.DataFrame,
    timezone_name: str,
    *,
    energy: Mapping[str, Any] | None = None,
    physical_energy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate completed daily observations through transparent activity lenses."""

    prepared, local_day = _prepare_frame(hourly, timezone_name)
    expected = _expected_hours(local_day, timezone_name)
    all_day_facts = _weather_facts(prepared, expected)
    commute = _commute_frame(prepared)
    commute_facts = _weather_facts(commute, 8)
    all_day_facts["solar_index"] = _supplemental_fact(
        energy, "solar_index", "index", "daily_energy.solar_index"
    )
    all_day_facts["pv_yield_kwh_per_kwp"] = _supplemental_fact(
        physical_energy,
        "pv_yield_kwh_per_kwp",
        "kWh/kWp",
        "daily_physical_energy.pv_yield_kwh_per_kwp",
    )

    lenses = [
        _evaluate_lens(
            spec,
            commute_facts if spec.scope == "commute-hours" else all_day_facts,
        )
        for spec in LENS_SPECS
    ]
    observed_hours = int(prepared["_time"].nunique())
    return {
        "schema": ACTIVITY_LENS_SCHEMA,
        "scope": "completed-observed-day",
        "date": local_day.isoformat(),
        "timezone": timezone_name,
        "disclaimer": DISCLAIMER,
        "evidence_quality": {
            "expected_hours": expected,
            "observed_hours": observed_hours,
            "coverage": round(min(observed_hours / expected, 1.0), 4),
            "minimum_lens_coverage": MINIMUM_EVIDENCE_COVERAGE,
        },
        "commute_windows": ["06:00-10:00", "15:00-19:00"],
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


def lens_by_id(document: Mapping[str, Any], lens_id: str) -> Mapping[str, Any]:
    """Return one lens from a generated document without hiding a missing id."""

    for lens in document.get("lenses", []):
        if lens.get("id") == lens_id:
            return lens
    raise KeyError(lens_id)


def available_lens_ids() -> tuple[str, ...]:
    return tuple(spec.id for spec in LENS_SPECS)
