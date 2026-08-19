from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FrontEvent:
    time: pd.Timestamp
    kind: str
    confidence: float
    score: int
    pressure_change_3h_hpa: float
    temperature_change_3h_c: float
    wind_shift_3h_deg: float
    precipitation_3h_mm: float
    briefing: str


@dataclass(frozen=True)
class FrontAnalysis:
    events: list[FrontEvent]
    diagnostics: pd.DataFrame
    notes: list[str]
    # No events means "no front passed" only when there was a series to search.
    # With no observations the honest answer is that the question was not asked.
    available: bool = True


def _angular_change(direction: pd.Series, periods: int = 3) -> pd.Series:
    difference = direction - direction.shift(periods)
    return ((difference + 180.0) % 360.0 - 180.0).abs()


def _weather_columns(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "temperature_2m": "temperature_c",
        "dew_point_2m": "dew_point_c",
        "pressure_msl": "pressure_msl_hpa",
        "wind_speed_10m": "wind_speed_ms",
        "wind_direction_10m": "wind_direction_deg",
        "wind_gusts_10m": "wind_gust_ms",
        "precipitation": "precipitation_mm",
    }
    prepared = frame.rename(columns=aliases).copy()
    prepared["time"] = pd.to_datetime(prepared["time"], utc=True)
    for column in [
        "temperature_c",
        "dew_point_c",
        "pressure_msl_hpa",
        "wind_speed_ms",
        "wind_direction_deg",
        "wind_gust_ms",
        "precipitation_mm",
    ]:
        if column not in prepared:
            prepared[column] = np.nan
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    return prepared


def detect_fronts(frame: pd.DataFrame) -> FrontAnalysis:
    if frame.empty:
        return FrontAnalysis(
            [],
            pd.DataFrame(),
            ["No surface observations were available for frontal analysis."],
            available=False,
        )
    prepared = _weather_columns(frame).set_index("time").sort_index()
    hourly = prepared.resample("1h").agg(
        {
            "temperature_c": "mean",
            "dew_point_c": "mean",
            "pressure_msl_hpa": "mean",
            "wind_speed_ms": "mean",
            "wind_direction_deg": "mean",
            "wind_gust_ms": "max",
            "precipitation_mm": "sum",
        }
    )
    hourly["pressure_change_3h_hpa"] = hourly["pressure_msl_hpa"].diff(3)
    hourly["temperature_change_3h_c"] = hourly["temperature_c"].diff(3)
    hourly["dewpoint_change_3h_c"] = hourly["dew_point_c"].diff(3)
    hourly["wind_speed_change_3h_ms"] = hourly["wind_speed_ms"].diff(3)
    hourly["wind_shift_3h_deg"] = _angular_change(hourly["wind_direction_deg"])
    hourly["precipitation_3h_mm"] = hourly["precipitation_mm"].rolling(3, min_periods=1).sum()

    signals = pd.DataFrame(index=hourly.index)
    signals["pressure"] = hourly["pressure_change_3h_hpa"].abs() >= 2.5
    signals["temperature"] = hourly["temperature_change_3h_c"].abs() >= 2.0
    signals["wind_shift"] = hourly["wind_shift_3h_deg"] >= 45.0
    signals["precipitation"] = hourly["precipitation_3h_mm"] >= 0.5
    signals["gust"] = hourly["wind_gust_ms"] >= 8.0
    signals["wind_speed"] = hourly["wind_speed_change_3h_ms"].abs() >= 2.0
    hourly["front_score"] = signals.sum(axis=1).astype(int)

    synoptic_anchor = signals["pressure"] | signals["precipitation"] | (hourly["wind_gust_ms"] >= 10.0)
    candidates = hourly[(hourly["front_score"] >= 3) & synoptic_anchor].copy()
    events: list[FrontEvent] = []
    if not candidates.empty:
        groups = (candidates.index.to_series().diff() > pd.Timedelta(hours=6)).cumsum()
        for _, group in candidates.groupby(groups):
            selected_time = group["front_score"].idxmax()
            row = hourly.loc[selected_time]
            temperature_change = float(row["temperature_change_3h_c"])
            if temperature_change <= -2.0:
                kind = "Probable cold-front passage"
            elif temperature_change >= 2.0:
                kind = "Probable warm-front passage"
            else:
                kind = "Probable frontal trough or wind-shift line"
            score = int(row["front_score"])
            confidence = min(0.45 + score * 0.085, 0.95)
            briefing = (
                f"{kind}: pressure changed {row['pressure_change_3h_hpa']:+.1f} hPa, "
                f"temperature {temperature_change:+.1f} C, wind shifted "
                f"{row['wind_shift_3h_deg']:.0f} degrees, and 3-hour precipitation was "
                f"{row['precipitation_3h_mm']:.1f} mm."
            )
            events.append(
                FrontEvent(
                    time=selected_time,
                    kind=kind,
                    confidence=round(confidence, 2),
                    score=score,
                    pressure_change_3h_hpa=float(row["pressure_change_3h_hpa"]),
                    temperature_change_3h_c=temperature_change,
                    wind_shift_3h_deg=float(row["wind_shift_3h_deg"]),
                    precipitation_3h_mm=float(row["precipitation_3h_mm"]),
                    briefing=briefing,
                )
            )
    notes = [
        "Frontal passages are objective candidates based on three-hour pressure, temperature, wind and precipitation changes.",
        "A pressure, precipitation or strong-gust anchor is required to suppress ordinary diurnal temperature and wind cycles.",
        "The detector identifies local passage signatures; it does not replace a manually analysed synoptic front.",
    ]
    return FrontAnalysis(events, hourly.reset_index(), notes)
