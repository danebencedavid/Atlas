from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from atlas.anomalies import Anomaly, weekly_metrics


@dataclass(frozen=True)
class RegimeClassification:
    label: str
    briefing: str
    daily_labels: list[str]
    signals: list[str]


def anomaly_lookup(anomalies: list[Anomaly]) -> dict[str, Anomaly]:
    return {item.metric: item for item in anomalies}


def classify_daily(group: pd.DataFrame) -> str:
    metrics = weekly_metrics(group)
    if metrics["precipitation_total_mm"] >= 8 and metrics["wind_speed_mean_ms"] >= 4:
        return "frontal"
    if metrics["shortwave_total_wh_m2"] >= 2500 and metrics["cloud_cover_mean_pct"] <= 45:
        return "sunny"
    if metrics["cloud_cover_mean_pct"] >= 75 and metrics["wind_speed_mean_ms"] < 3:
        return "stagnant"
    if metrics["temperature_mean_c"] >= 27:
        return "hot"
    if metrics["frost_hours"] >= 3:
        return "frost"
    return "mixed"


def classify_week(frame: pd.DataFrame, anomalies: list[Anomaly]) -> RegimeClassification:
    metrics = weekly_metrics(frame)
    lookup = anomaly_lookup(anomalies)
    temp_z = lookup["temperature_mean_c"].z_score
    precip_z = lookup["precipitation_total_mm"].z_score
    wind_z = lookup["wind_speed_mean_ms"].z_score
    pressure_z = lookup["pressure_mean_hpa"].z_score
    cloud_z = lookup["cloud_cover_mean_pct"].z_score
    radiation_z = lookup["shortwave_total_wh_m2"].z_score

    signals: list[str] = []
    label = "Mixed transition week"

    if radiation_z >= 0.7 and cloud_z <= -0.5 and precip_z <= -0.4 and pressure_z >= 0:
        label = "Sunny high-pressure week"
        signals.extend(["above-normal radiation", "reduced cloudiness", "limited rainfall"])
    elif wind_z <= -0.5 and cloud_z >= 0.6 and radiation_z <= -0.6:
        label = "Cloudy stagnant week"
        signals.extend(["weak wind", "persistent cloud", "suppressed solar radiation"])
    elif precip_z >= 0.8 and metrics["pressure_range_hpa"] >= 10:
        label = "Wet frontal week"
        signals.extend(["rain surplus", "notable pressure swings"])
    elif wind_z >= 0.9 and metrics["pressure_range_hpa"] >= 10:
        label = "Windy frontal week"
        signals.extend(["wind surplus", "active pressure pattern"])
    elif temp_z >= 1.0 and metrics["cooling_degree_days_c"] >= 12:
        label = "Heat-stress week"
        signals.extend(["warm anomaly", "cooling-degree demand"])
    elif temp_z <= -1.0 and metrics["frost_hours"] >= 6:
        label = "Cold/frost-prone week"
        signals.extend(["cold anomaly", "frost-prone hours"])
    else:
        signals.extend(["no single signal dominated", "mixed day-to-day conditions"])

    local_days = frame.copy()
    if "local_time" in local_days:
        local_days["day"] = pd.to_datetime(local_days["local_time"]).dt.date
    else:
        local_days["day"] = pd.to_datetime(local_days["time"]).dt.date
    daily_labels = [classify_daily(group) for _, group in local_days.groupby("day")]

    briefing = make_briefing(label, lookup)
    return RegimeClassification(label=label, briefing=briefing, daily_labels=daily_labels, signals=signals)


def make_briefing(label: str, lookup: dict[str, Anomaly]) -> str:
    temp = lookup["temperature_mean_c"].anomaly
    precip = lookup["precipitation_total_mm"].anomaly
    wind = lookup["wind_speed_mean_ms"].anomaly
    solar = lookup["shortwave_total_wh_m2"].anomaly
    return (
        f"{label}: temperature was {temp:+.1f} deg C versus normal, "
        f"precipitation {precip:+.1f} mm, wind {wind:+.1f} m/s, "
        f"and weekly solar radiation {solar:+.0f} Wh/m2."
    )
