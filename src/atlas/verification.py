"""Verification of the ERA5 reanalysis against the HungaroMet station.

Every other page treats the reanalysis as ground truth. This one asks how far it
sat from the instrument at Debrecen Airport over the same hours, so a reader can
judge how much weight the rest of the analysis deserves on any given day.

The comparison is deliberately plain: hourly pairs, no detrending, no quality
filtering beyond dropping hours where either source is missing. Reanalysis minus
station throughout, so a positive bias means ERA5 read high.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from atlas.hungaromet import StationObservations, station_hourly


# Reanalysis column, station column, label, unit, and whether the pair is an
# accumulation rather than an instantaneous reading.
VERIFICATION_PAIRS: list[tuple[str, str, str, str, bool]] = [
    ("temperature_2m", "temperature_c", "Temperature", "°C", False),
    ("dew_point_2m", "dew_point_c", "Dew point", "°C", False),
    ("relative_humidity_2m", "relative_humidity_pct", "Relative humidity", "%", False),
    ("pressure_msl", "pressure_msl_hpa", "Mean sea-level pressure", "hPa", False),
    ("wind_speed_10m", "wind_speed_ms", "Wind speed", "m/s", False),
    ("wind_gusts_10m", "wind_gust_ms", "Wind gust", "m/s", False),
    ("precipitation", "precipitation_mm", "Precipitation", "mm", True),
]

# Below this many paired hours the scores say more about the sampling than about
# the reanalysis, so they are reported but flagged.
MINIMUM_RELIABLE_PAIRS = 12


@dataclass(frozen=True)
class VariableVerification:
    key: str
    label: str
    unit: str
    pairs: int
    bias: float
    mean_absolute_error: float
    root_mean_square_error: float
    correlation: float | None
    station_mean: float
    reanalysis_mean: float
    accumulated: bool

    @property
    def reliable(self) -> bool:
        return self.pairs >= MINIMUM_RELIABLE_PAIRS


@dataclass(frozen=True)
class StationVerification:
    station_name: str
    station_id: int | None
    hours_compared: int
    variables: list[VariableVerification]
    notes: list[str]

    @property
    def headline(self) -> VariableVerification | None:
        """Temperature carries the summary; it is the reading people check first."""
        for variable in self.variables:
            if variable.key == "temperature_2m":
                return variable
        return self.variables[0] if self.variables else None


def _score(
    key: str,
    label: str,
    unit: str,
    accumulated: bool,
    reanalysis: pd.Series,
    station: pd.Series,
) -> VariableVerification | None:
    paired = pd.DataFrame({"reanalysis": reanalysis, "station": station}).dropna()
    if paired.empty:
        return None
    difference = paired["reanalysis"] - paired["station"]
    # Correlation is undefined when either series is flat, which happens for
    # precipitation on dry days far more often than it looks like it should.
    correlation: float | None = None
    if len(paired) > 2 and paired["reanalysis"].std() > 0 and paired["station"].std() > 0:
        correlation = float(paired["reanalysis"].corr(paired["station"]))
        if not np.isfinite(correlation):
            correlation = None
    return VariableVerification(
        key=key,
        label=label,
        unit=unit,
        pairs=int(len(paired)),
        bias=float(difference.mean()),
        mean_absolute_error=float(difference.abs().mean()),
        root_mean_square_error=float(np.sqrt((difference**2).mean())),
        correlation=correlation,
        station_mean=float(paired["station"].mean()),
        reanalysis_mean=float(paired["reanalysis"].mean()),
        accumulated=accumulated,
    )


def verify_against_station(
    reanalysis: pd.DataFrame,
    observations: StationObservations,
) -> StationVerification:
    """Score the reanalysis against the station over their overlapping hours."""
    notes: list[str] = []
    hourly = station_hourly(observations)
    if reanalysis.empty or hourly.empty or "time" not in reanalysis:
        return StationVerification(
            station_name=observations.station_name,
            station_id=observations.station_id,
            hours_compared=0,
            variables=[],
            notes=["No overlapping station hours were available for verification."],
        )

    left = reanalysis.copy()
    left["time"] = pd.to_datetime(left["time"], utc=True).dt.floor("h")
    right = hourly.copy()
    right["time"] = pd.to_datetime(right["time"], utc=True).dt.floor("h")
    merged = left.merge(right, on="time", how="inner", suffixes=("_era5", "_station"))
    if merged.empty:
        return StationVerification(
            station_name=observations.station_name,
            station_id=observations.station_id,
            hours_compared=0,
            variables=[],
            notes=["The reanalysis and the station shared no common hours."],
        )

    variables: list[VariableVerification] = []
    for reanalysis_column, station_column, label, unit, accumulated in VERIFICATION_PAIRS:
        # A column present in both frames is suffixed by the merge; one present in
        # only one keeps its name.
        left_name = reanalysis_column if reanalysis_column in merged else f"{reanalysis_column}_era5"
        right_name = station_column if station_column in merged else f"{station_column}_station"
        if left_name not in merged or right_name not in merged:
            continue
        scored = _score(
            reanalysis_column,
            label,
            unit,
            accumulated,
            pd.to_numeric(merged[left_name], errors="coerce"),
            pd.to_numeric(merged[right_name], errors="coerce"),
        )
        if scored is not None:
            variables.append(scored)

    if not variables:
        notes.append("No variable was reported by both sources over the period.")
    thin = [variable.label for variable in variables if not variable.reliable]
    if thin:
        notes.append(
            "Fewer than "
            f"{MINIMUM_RELIABLE_PAIRS} paired hours for {', '.join(thin)}; "
            "treat those scores as indicative only."
        )
    notes.extend(observations.notes)
    return StationVerification(
        station_name=observations.station_name,
        station_id=observations.station_id,
        hours_compared=int(len(merged)),
        variables=variables,
        notes=notes,
    )
