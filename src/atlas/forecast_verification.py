"""Pair archived forecasts with ground truth and score the raw NWP error.

Ground truth is the HungaroMet station at Debrecen Airport. ERA5 is used only
where the station has no observation for an hour, and every such row is marked
``truth_source == "era5"`` so it can be excluded or inspected. Nothing is ever
substituted silently.

Timezone handling is the most likely source of a silent correctness bug here, so
everything internal is UTC and the joins assert it rather than trusting it. A
one-hour misalignment would show up as a plausible-looking diurnal bias rather
than as an error.

This module verifies. It does not model: no correction is fitted, and no value is
adjusted. Stage 2 builds on the pairs this produces.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from atlas.config import AtlasConfig
from atlas.hungaromet import StationObservations, station_hourly

# Archive variable -> the station column carrying the same quantity.
STATION_EQUIVALENTS: dict[str, str] = {
    "temperature_2m": "temperature_c",
    "wind_speed_10m": "wind_speed_ms",
    "wind_gusts_10m": "wind_gust_ms",
    "relative_humidity_2m": "relative_humidity_pct",
}

# Archive variable -> the ERA5 column in the repo's existing hourly analysis frame.
ERA5_EQUIVALENTS: dict[str, str] = {
    "temperature_2m": "temperature_2m",
    "wind_speed_10m": "wind_speed_10m",
    "wind_gusts_10m": "wind_gusts_10m",
    "relative_humidity_2m": "relative_humidity_2m",
    "shortwave_radiation": "shortwave_radiation",
    "direct_radiation": "direct_radiation",
    "diffuse_radiation": "diffuse_radiation",
    "cloud_cover": "cloud_cover",
}

IRRADIANCE_CAVEAT = (
    "verified against ERA5 reanalysis, not observations; not validated against "
    "measured irradiance"
)

# Irradiance is never verified against the station: HungaroMet's 10-minute export
# carries no radiation channel, so ERA5 is the only available truth for it.
IRRADIANCE_VARIABLES = {"shortwave_radiation", "direct_radiation", "diffuse_radiation"}

SEASONS = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
           6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}


@dataclass(frozen=True)
class PairingResult:
    pairs: pd.DataFrame
    notes: list[str]

    @property
    def available(self) -> bool:
        return not self.pairs.empty


def _assert_utc(frame: pd.DataFrame, column: str, label: str) -> None:
    """Fail loudly on a naive or non-UTC timestamp column.

    Asserted rather than coerced: a silent conversion here would shift every pair
    by the local offset and produce a diurnal bias that looks like real physics.
    """
    if frame.empty:
        return
    dtype = frame[column].dtype
    tz = getattr(dtype, "tz", None)
    if tz is None:
        raise AssertionError(f"{label}.{column} is timezone-naive; everything internal must be UTC.")
    if str(tz) != "UTC":
        raise AssertionError(f"{label}.{column} is in {tz}, not UTC.")


def build_truth_table(
    station: StationObservations,
    era5: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Long-format hourly truth, station first and ERA5 only to fill gaps."""
    notes: list[str] = []
    frames: list[pd.DataFrame] = []

    hourly = station_hourly(station)
    if not hourly.empty:
        hourly = hourly.copy()
        hourly["time"] = pd.to_datetime(hourly["time"], utc=True)
        _assert_utc(hourly, "time", "station_hourly")
        for variable, column in STATION_EQUIVALENTS.items():
            if column not in hourly:
                continue
            series = pd.to_numeric(hourly[column], errors="coerce")
            frames.append(
                pd.DataFrame(
                    {
                        "valid_time_utc": hourly["time"],
                        "variable": variable,
                        "observed": series,
                        "truth_source": "station",
                    }
                ).dropna(subset=["observed"])
            )
        notes.append(
            f"Station truth: {len(hourly):,} hourly records "
            f"{hourly['time'].min()} to {hourly['time'].max()}."
        )
    else:
        notes.append("No station observations were available; ERA5 is the only truth source.")

    if era5 is not None and not era5.empty:
        era5 = era5.copy()
        era5["time"] = pd.to_datetime(era5["time"], utc=True)
        _assert_utc(era5, "time", "era5")
        for variable, column in ERA5_EQUIVALENTS.items():
            if column not in era5:
                continue
            series = pd.to_numeric(era5[column], errors="coerce")
            frames.append(
                pd.DataFrame(
                    {
                        "valid_time_utc": era5["time"],
                        "variable": variable,
                        "observed": series,
                        "truth_source": "era5",
                    }
                ).dropna(subset=["observed"])
            )
        notes.append(f"ERA5 fallback available for {len(ERA5_EQUIVALENTS)} variables.")

    if not frames:
        return pd.DataFrame(columns=["valid_time_utc", "variable", "observed", "truth_source"]), notes

    truth = pd.concat(frames, ignore_index=True)
    # Station wins wherever both exist; ERA5 only fills the gaps it leaves.
    truth["priority"] = np.where(truth["truth_source"] == "station", 0, 1)
    truth = (
        truth.sort_values(["valid_time_utc", "variable", "priority"])
        .drop_duplicates(subset=["valid_time_utc", "variable"], keep="first")
        .drop(columns=["priority"])
        .reset_index(drop=True)
    )
    return truth, notes


def pair_forecasts_with_truth(
    forecasts: pd.DataFrame,
    truth: pd.DataFrame,
) -> PairingResult:
    """Inner-join forecasts to truth on valid time and variable."""
    notes: list[str] = []
    if forecasts.empty or truth.empty:
        return PairingResult(pd.DataFrame(), ["No forecasts or no truth were available to pair."])

    # Asserted before any coercion: pd.to_datetime(..., utc=True) would happily
    # localise a naive column and shift every pair by the local offset without
    # complaining, which is the silent bug this check exists to catch.
    _assert_utc(forecasts, "valid_time_utc", "forecasts")
    _assert_utc(truth, "valid_time_utc", "truth")
    forecasts = forecasts.copy()
    truth = truth.copy()

    pairs = forecasts.merge(truth, on=["valid_time_utc", "variable"], how="inner")
    if pairs.empty:
        return PairingResult(pd.DataFrame(), ["Forecasts and truth shared no valid hours."])

    pairs["error"] = pairs["value"] - pairs["observed"]
    pairs["hour_utc"] = pairs["valid_time_utc"].dt.hour
    pairs["month"] = pairs["valid_time_utc"].dt.month
    pairs["season"] = pairs["month"].map(SEASONS)

    unmatched = len(forecasts) - len(pairs)
    if unmatched > 0:
        notes.append(
            f"{unmatched:,} forecast rows had no matching observation and were dropped."
        )
    era5_rows = int((pairs["truth_source"] == "era5").sum())
    if era5_rows:
        notes.append(
            f"{era5_rows:,} of {len(pairs):,} pairs ({era5_rows / len(pairs):.1%}) fall back to "
            "ERA5 and are marked truth_source=era5."
        )
    return PairingResult(pairs.reset_index(drop=True), notes)


def _scores(group: pd.DataFrame) -> pd.Series:
    error = group["error"]
    return pd.Series(
        {
            "n": int(len(group)),
            "bias": float(error.mean()),
            "mae": float(error.abs().mean()),
            "rmse": float(np.sqrt((error**2).mean())),
        }
    )


def score(pairs: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Bias, MAE and RMSE grouped by the given keys, with sample sizes."""
    if pairs.empty:
        return pd.DataFrame(columns=[*by, "n", "bias", "mae", "rmse"])
    return (
        pairs.groupby(by, observed=True)
        .apply(_scores, include_groups=False)
        .reset_index()
        .sort_values(by)
        .reset_index(drop=True)
    )


def clear_sky_index(pairs: pd.DataFrame, config: AtlasConfig) -> pd.DataFrame:
    """Add a clear-sky index and regime label for irradiance rows.

    The index is observed global irradiance over a clear-sky estimate from solar
    geometry, which separates overcast from broken from clear conditions. Errors
    behave very differently across those regimes, so a single irradiance score
    hides most of what matters.
    """
    if pairs.empty:
        return pairs.assign(clear_sky_index=np.nan, sky_regime=pd.NA)
    out = pairs.copy()
    latitude = np.radians(config.location.latitude)
    day_of_year = out["valid_time_utc"].dt.dayofyear
    # Solar position, sufficient for a regime split rather than an energy estimate.
    declination = np.radians(23.45) * np.sin(2 * np.pi * (284 + day_of_year) / 365.25)
    hour_angle = np.radians(15.0 * (out["valid_time_utc"].dt.hour + config.location.longitude / 15.0 - 12.0))
    cos_zenith = np.sin(latitude) * np.sin(declination) + np.cos(latitude) * np.cos(declination) * np.cos(
        hour_angle
    )
    cos_zenith = cos_zenith.clip(lower=0.0)
    clear_sky = 1361.0 * 0.75 * cos_zenith

    index = pd.Series(np.nan, index=out.index, dtype=float)
    daylight = clear_sky > 50.0
    index[daylight] = (out.loc[daylight, "observed"] / clear_sky[daylight]).clip(0.0, 1.5)
    out["clear_sky_index"] = index
    out["sky_regime"] = pd.cut(
        index,
        bins=[-0.01, 0.35, 0.7, 1.6],
        labels=["overcast", "broken", "clear"],
    )
    # Night has no meaningful irradiance error to classify.
    out.loc[~daylight, "sky_regime"] = pd.NA
    return out
