"""CAMS Radiation Service ingestion for irradiance ground truth.

ERA5 is model output. Correcting a forecast toward it measures agreement between
two models rather than skill against reality, so irradiance verified only against
ERA5 cannot support any external claim. CAMS is satellite-derived and is the
closest thing to an observation available for a single point in Debrecen.

It is still not a ground measurement. Satellite retrieval infers surface
irradiance from what the sensor sees above, and that inference degrades over
bright surfaces: fresh snow can be mistaken for cloud and vice versa. Winter
errors therefore deserve separate inspection rather than being folded into an
annual average.

Access needs a personal ADS token. It is read from the environment and never
written to the tree, so neither a token nor a .cdsapirc belongs in this
repository. The retrieve API is a plain job API, so it is driven with ``requests``
like every other ingestion module here rather than through the vendor client.
"""

from __future__ import annotations

import io
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from atlas.config import AtlasConfig

ADS_ROOT = "https://ads.atmosphere.copernicus.eu/api/retrieve/v1"

ATTRIBUTION = (
    "Irradiance ground truth from the CAMS Radiation Service via the Copernicus "
    "Atmosphere Data Store, licensed CC BY 4.0 "
    "(https://creativecommons.org/licenses/by/4.0/). Values are modified: they are "
    "paired with forecasts and used to compute error statistics by Atlas."
)

# The wording every irradiance surface must carry. CAMS is satellite-derived, so
# "observation" would overstate it.
IRRADIANCE_CAVEAT = (
    "verified against CAMS satellite-derived irradiance, not ground measurement"
)
SNOW_CAVEAT = (
    "Satellite irradiance retrieval degrades over snow cover, where a bright "
    "surface is readily confused with cloud, so winter errors are reported "
    "separately rather than folded into an annual average."
)

# CAMS column name -> the archive variable it verifies.
CAMS_COLUMNS: dict[str, str] = {
    "GHI": "shortwave_radiation",
    "BHI": "direct_radiation",
    "DHI": "diffuse_radiation",
}


class CamsCredentialError(RuntimeError):
    """Raised when the ADS token is absent, with instructions rather than a stack."""


@dataclass(frozen=True)
class CamsRadiation:
    frame: pd.DataFrame
    notes: list[str]

    @property
    def available(self) -> bool:
        return not self.frame.empty


def read_token(config: AtlasConfig) -> str:
    """Read the ADS token from the environment, or explain how to supply it."""
    variable = config.cams.token_env_var
    token = os.environ.get(variable, "").strip()
    if not token:
        raise CamsCredentialError(
            f"The CAMS Radiation Service needs a personal ADS token in ${variable}, "
            "which is not set.\n"
            "  1. Register at https://ads.atmosphere.copernicus.eu and accept the "
            "dataset licence.\n"
            "  2. Copy the personal access token from your ADS profile page.\n"
            f"  3. Set it in your shell, for example: $env:{variable}='<token>' "
            "(PowerShell) or export "
            f"{variable}=<token> (bash).\n"
            "In CI, provide it as a repository secret of the same name. The token is "
            "never written into this repository."
        )
    return token


def _cache_path(config: AtlasConfig, start: date, end: date) -> Path:
    return (
        config.outputs.data_dir
        / "raw"
        / "cams"
        / f"cams_radiation_{start.isoformat()}_{end.isoformat()}.csv"
    )


def _submit(config: AtlasConfig, token: str, start: date, end: date) -> str:
    """Start a retrieve job and return the URL of its result when it finishes."""
    settings = config.cams
    session = requests.Session()
    session.headers.update({"PRIVATE-TOKEN": token, "Accept": "application/json"})
    payload: dict[str, Any] = {
        "inputs": {
            "sky_type": settings.sky_type,
            "location": {
                "latitude": config.location.latitude,
                "longitude": config.location.longitude,
            },
            "altitude": settings.altitude,
            "date": f"{start.isoformat()}/{end.isoformat()}",
            "time_step": settings.time_step,
            "time_reference": "universal_time",
            # The schema names this data_format, not format.
            "data_format": "csv",
        }
    }
    response = session.post(
        f"{ADS_ROOT}/processes/{settings.dataset}/execution",
        json=payload,
        timeout=settings.request_timeout_seconds,
    )
    if response.status_code in (401, 403):
        # The ADS distinguishes a bad token (401) from a valid token whose account
        # has not accepted the dataset licence (403), and its own detail names the
        # page to visit. Passing that through beats guessing at the cause.
        try:
            problem = response.json()
            detail = problem.get("detail") or problem.get("title") or response.text
        except ValueError:
            detail = response.text
        cause = (
            "the token was rejected"
            if response.status_code == 401
            else "the token is valid but the account lacks permission"
        )
        raise CamsCredentialError(
            f"The ADS refused the request (HTTP {response.status_code}): {cause}.\n"
            f"  {str(detail).strip()}\n"
            f"The token comes from ${settings.token_env_var}."
        )
    response.raise_for_status()
    job = response.json()
    job_id = job.get("jobID") or job.get("job_id")
    if not job_id:
        raise RuntimeError(f"The ADS did not return a job id: {job}")

    for _ in range(settings.poll_attempts):
        status = session.get(
            f"{ADS_ROOT}/jobs/{job_id}", timeout=settings.request_timeout_seconds
        )
        status.raise_for_status()
        state = status.json().get("status")
        if state == "successful":
            break
        if state in {"failed", "dismissed"}:
            raise RuntimeError(f"The ADS job {job_id} ended as {state}.")
        time.sleep(settings.poll_seconds)
    else:
        raise RuntimeError(
            f"The ADS job {job_id} did not finish within "
            f"{settings.poll_attempts * settings.poll_seconds:.0f} seconds."
        )

    results = session.get(
        f"{ADS_ROOT}/jobs/{job_id}/results", timeout=settings.request_timeout_seconds
    )
    results.raise_for_status()
    asset = results.json().get("asset", {}).get("value", {})
    href = asset.get("href")
    if not href:
        raise RuntimeError(f"The ADS job {job_id} produced no downloadable asset.")
    return href


def parse_cams_csv(text: str) -> pd.DataFrame:
    """Parse a CAMS time-series export into hourly UTC irradiance in W/m^2.

    The export is semicolon-separated with a commented header, and its period
    column is an ISO interval. CAMS reports energy over the interval in Wh/m^2,
    which for hourly steps is numerically the mean power in W/m^2.

    The interval *end* is the valid time. CAMS labels each row by the start of
    the hour it integrates over; Open-Meteo labels hourly radiation by the end of
    the hour it averages over, as the preceding-hour mean. Taking the start put
    every irradiance pair one hour out of step, which inflated shortwave MAE at
    24 h from 32 to 55 W/m^2 and left a one-hour shift sitting in the residual
    for any correction to discover and remove. The offset survives averaging, so
    nothing in a seasonal or diurnal summary reveals it.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    header_index = next(
        (index for index, line in enumerate(lines) if line.lstrip("# ").startswith("Observation period")),
        None,
    )
    if header_index is None:
        raise ValueError("The CAMS export did not contain an observation-period header.")
    body = "\n".join(line.lstrip("# ") for line in lines[header_index:])
    frame = pd.read_csv(io.StringIO(body), sep=";")
    frame.columns = [column.strip() for column in frame.columns]

    period = frame["Observation period"].astype(str)
    # The interval end is the valid hour, matching Open-Meteo's preceding-hour
    # convention. Everything internal stays UTC.
    ends = pd.to_datetime(period.str.split("/").str[1], utc=True, errors="coerce")
    output = pd.DataFrame({"time": ends})
    for source, target in CAMS_COLUMNS.items():
        if source in frame:
            output[target] = pd.to_numeric(frame[source], errors="coerce")
    return output.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)


def fetch_cams_radiation(
    config: AtlasConfig,
    start: date,
    end: date,
    refresh: bool = False,
) -> CamsRadiation:
    """Fetch hourly CAMS irradiance for the configured point, month by month."""
    settings = config.cams
    if not settings.enabled:
        return CamsRadiation(pd.DataFrame(), ["CAMS ingestion is disabled."])

    token: str | None = None
    frames: list[pd.DataFrame] = []
    notes: list[str] = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=settings.chunk_days - 1), end)
        cache = _cache_path(config, cursor, stop)
        if cache.exists() and not refresh:
            text = cache.read_text(encoding="utf-8")
        else:
            # Deferred so a fully cached run never needs a token at all.
            token = token or read_token(config)
            href = _submit(config, token, cursor, stop)
            download = requests.get(href, timeout=settings.request_timeout_seconds)
            download.raise_for_status()
            text = download.text
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
        try:
            frames.append(parse_cams_csv(text))
        except ValueError as exc:
            notes.append(f"{cursor.isoformat()} to {stop.isoformat()}: {exc}")
        cursor = stop + timedelta(days=1)

    if not frames:
        return CamsRadiation(pd.DataFrame(), notes or ["No CAMS data was retrieved."])
    frame = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["time"], keep="last")
        .sort_values("time")
        .reset_index(drop=True)
    )
    notes.insert(
        0,
        f"CAMS Radiation Service, {settings.sky_type} sky, {settings.time_step} steps: "
        f"{len(frame):,} hours {frame['time'].min()} to {frame['time'].max()}.",
    )
    notes.append(ATTRIBUTION)
    notes.append(SNOW_CAVEAT)
    return CamsRadiation(frame, notes)
