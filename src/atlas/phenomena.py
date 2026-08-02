from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from atlas.fronts import FrontAnalysis
from atlas.hungaromet import LightningArchive, RadarArchive, StationObservations, station_hourly
from atlas.profile import ModelProfile


@dataclass(frozen=True)
class WeatherPhenomenon:
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    kind: str
    evidence: str
    confidence: float
    source: str


@dataclass(frozen=True)
class PhenomenaAnalysis:
    events: list[WeatherPhenomenon]
    notes: list[str]


def _runs(frame: pd.DataFrame, mask: pd.Series) -> list[pd.DataFrame]:
    selected = frame.loc[mask.fillna(False)].copy()
    if selected.empty:
        return []
    selected = selected.sort_values("time")
    groups = (selected["time"].diff() > pd.Timedelta(hours=1, minutes=30)).cumsum()
    return [group for _, group in selected.groupby(groups)]


def _surface_source(
    weather: pd.DataFrame,
    station: StationObservations,
) -> tuple[pd.DataFrame, str, float]:
    observed = station_hourly(station)
    if not observed.empty:
        return observed, f"HungaroMet station {station.station_id}", 0.92
    aliases = {
        "temperature_2m": "temperature_c",
        "dew_point_2m": "dew_point_c",
        "relative_humidity_2m": "relative_humidity_pct",
        "precipitation": "precipitation_mm",
        "wind_gusts_10m": "wind_gust_ms",
    }
    return weather.rename(columns=aliases).copy(), "Open-Meteo gridded surface analysis", 0.68


def _append_runs(
    events: list[WeatherPhenomenon],
    frame: pd.DataFrame,
    mask: pd.Series,
    kind: str,
    source: str,
    confidence: float,
    evidence_builder,
) -> None:
    for group in _runs(frame, mask):
        events.append(
            WeatherPhenomenon(
                start_time=pd.Timestamp(group["time"].iloc[0]),
                end_time=pd.Timestamp(group["time"].iloc[-1]) + pd.Timedelta(hours=1),
                kind=kind,
                evidence=evidence_builder(group),
                confidence=confidence,
                source=source,
            )
        )


def detect_weather_phenomena(
    weather: pd.DataFrame,
    station: StationObservations,
    radar: RadarArchive,
    lightning: LightningArchive,
    fronts: FrontAnalysis,
    profile: ModelProfile,
    timezone_name: str,
) -> PhenomenaAnalysis:
    events: list[WeatherPhenomenon] = []
    surface, surface_source, surface_confidence = _surface_source(weather, station)
    surface["time"] = pd.to_datetime(surface["time"], utc=True)
    for column in [
        "temperature_c",
        "dew_point_c",
        "relative_humidity_pct",
        "visibility_m",
        "precipitation_mm",
        "wind_gust_ms",
    ]:
        if column not in surface:
            surface[column] = np.nan
        surface[column] = pd.to_numeric(surface[column], errors="coerce")

    humid = (surface["relative_humidity_pct"] >= 95) | (
        surface["temperature_c"] - surface["dew_point_c"] <= 1.2
    )
    fog_mask = (surface["visibility_m"] <= 1000) & humid
    _append_runs(
        events,
        surface,
        fog_mask,
        "Fog",
        surface_source,
        surface_confidence,
        lambda group: (
            f"Minimum visibility {group['visibility_m'].min():.0f} m with "
            f"maximum relative humidity {group['relative_humidity_pct'].max():.0f}%."
        ),
    )
    low_visibility_mask = (
        (surface["visibility_m"] > 1000)
        & (surface["visibility_m"] <= 5000)
        & humid
    )
    _append_runs(
        events,
        surface,
        low_visibility_mask,
        "Low visibility",
        surface_source,
        max(surface_confidence - 0.05, 0.5),
        lambda group: f"Minimum visibility {group['visibility_m'].min():.0f} m in saturated or near-saturated air.",
    )

    frost_mask = surface["temperature_c"] <= 0.0
    _append_runs(
        events,
        surface,
        frost_mask,
        "Frost",
        surface_source,
        surface_confidence,
        lambda group: f"Minimum temperature {group['temperature_c'].min():.1f} C.",
    )
    heat_mask = surface["temperature_c"] >= 30.0
    _append_runs(
        events,
        surface,
        heat_mask,
        "Heat stress",
        surface_source,
        surface_confidence,
        lambda group: (
            f"Temperature remained at or above 30 C and peaked at "
            f"{group['temperature_c'].max():.1f} C."
        ),
    )

    surface["precipitation_3h_mm"] = surface["precipitation_mm"].rolling(3, min_periods=1).sum()
    heavy_rain_mask = (surface["precipitation_mm"] >= 5.0) | (
        surface["precipitation_3h_mm"] >= 10.0
    )
    _append_runs(
        events,
        surface,
        heavy_rain_mask,
        "Heavy rain",
        surface_source,
        surface_confidence,
        lambda group: (
            f"Peak hourly precipitation {group['precipitation_mm'].max():.1f} mm; "
            f"maximum rolling three-hour total {group['precipitation_3h_mm'].max():.1f} mm."
        ),
    )
    gust_mask = surface["wind_gust_ms"] >= 15.0
    _append_runs(
        events,
        surface,
        gust_mask,
        "Strong gusts",
        surface_source,
        surface_confidence,
        lambda group: f"Peak gust {group['wind_gust_ms'].max():.1f} m/s.",
    )

    if "snowfall" in weather:
        snow = weather[["time", "temperature_2m", "snowfall"]].copy()
        snow["time"] = pd.to_datetime(snow["time"], utc=True)
        snow["snowfall"] = pd.to_numeric(snow["snowfall"], errors="coerce")
        snow["temperature_2m"] = pd.to_numeric(snow["temperature_2m"], errors="coerce")
        for group in _runs(snow, snow["snowfall"] > 0):
            kind = "Snow" if group["temperature_2m"].mean() <= 1.0 else "Mixed precipitation"
            events.append(
                WeatherPhenomenon(
                    pd.Timestamp(group["time"].iloc[0]),
                    pd.Timestamp(group["time"].iloc[-1]) + pd.Timedelta(hours=1),
                    kind,
                    f"Model snowfall total {group['snowfall'].sum():.1f} cm with mean 2 m temperature {group['temperature_2m'].mean():.1f} C.",
                    0.62,
                    "Open-Meteo gridded surface analysis",
                )
            )

    if not lightning.hourly.empty:
        thunder = lightning.hourly.copy()
        thunder["time"] = pd.to_datetime(thunder["time"], utc=True)
        radar_timeline = radar.timeline.copy()
        if not radar_timeline.empty:
            radar_timeline["time"] = pd.to_datetime(radar_timeline["time"], utc=True)
            radar_hourly = (
                radar_timeline.set_index("time")["domain_max_dbz"]
                .resample("1h")
                .max()
                .rename("radar_max_dbz")
                .reset_index()
            )
            thunder = thunder.merge(radar_hourly, on="time", how="left")
        else:
            thunder["radar_max_dbz"] = np.nan
        for group in _runs(thunder, thunder["flash_count"] > 0):
            radar_max = pd.to_numeric(group["radar_max_dbz"], errors="coerce").max()
            evidence = f"{int(group['flash_count'].sum())} LINET event(s)"
            confidence = 0.86
            if np.isfinite(radar_max):
                evidence += f" with radar reflectivity reaching {radar_max:.1f} dBZ"
                confidence = 0.96 if radar_max >= 35 else 0.90
            events.append(
                WeatherPhenomenon(
                    pd.Timestamp(group["time"].iloc[0]),
                    pd.Timestamp(group["time"].iloc[-1]) + pd.Timedelta(hours=1),
                    "Thunderstorm",
                    evidence + ".",
                    confidence,
                    "HungaroMet LINET and composite radar",
                )
            )

    if not profile.series.empty and {1000.0, 925.0}.issubset(
        set(pd.to_numeric(profile.series["pressure_hpa"], errors="coerce").dropna())
    ):
        levels = profile.series.pivot_table(
            index="time", columns="pressure_hpa", values="temperature_c", aggfunc="mean"
        ).reset_index()
        levels["time"] = pd.to_datetime(levels["time"], utc=True)
        levels["inversion_strength_c"] = levels[925.0] - levels[1000.0]
        local_hour = levels["time"].dt.tz_convert(timezone_name).dt.hour
        inversion_mask = (levels["inversion_strength_c"] >= 1.0) & (
            (local_hour >= 18) | (local_hour < 8)
        )
        _append_runs(
            events,
            levels,
            inversion_mask,
            "Nocturnal low-level inversion",
            "Open-Meteo historical-model pressure levels",
            0.66,
            lambda group: (
                f"925 hPa temperature exceeded 1000 hPa temperature by as much as "
                f"{group['inversion_strength_c'].max():.1f} C during local night."
            ),
        )

    for front in fronts.events:
        events.append(
            WeatherPhenomenon(
                front.time,
                front.time + pd.Timedelta(hours=1),
                front.kind,
                front.briefing,
                front.confidence,
                "Objective compound surface-change detector",
            )
        )

    events.sort(key=lambda item: (item.start_time, item.kind))
    notes = [
        "Phenomena are deterministic candidates based on explicit thresholds; they are not manually quality-controlled reports.",
        "Observed station evidence is preferred, with gridded or model-derived evidence identified when observations are unavailable.",
    ]
    return PhenomenaAnalysis(events, notes)
