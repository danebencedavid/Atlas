from __future__ import annotations

from atlas.anomalies import Anomaly
from atlas.energy import EnergyIndex
from atlas.regimes import RegimeClassification


def public_summary(regime: RegimeClassification, energy: EnergyIndex, anomalies: list[Anomaly]) -> str:
    temperature = next(item for item in anomalies if item.metric == "temperature_mean_c")
    precipitation = next(item for item in anomalies if item.metric == "precipitation_total_mm")
    return (
        f"{regime.label} with a {temperature.anomaly:+.1f} deg C temperature anomaly, "
        f"{precipitation.anomaly:+.1f} mm precipitation anomaly, and a "
        f"{energy.label} renewable-weather profile."
    )
