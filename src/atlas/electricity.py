from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from atlas.config import AtlasConfig
from atlas.ingest import fetch_json_with_retry


ENERGY_CHARTS_URL = "https://api.energy-charts.info"


@dataclass(frozen=True)
class ElectricityData:
    frame: pd.DataFrame
    source: str
    notes: list[str]


@dataclass(frozen=True)
class ElectricitySummary:
    available: bool
    average_load_mw: float
    peak_load_mw: float
    solar_generation_mwh: float
    wind_generation_mwh: float
    renewable_share_mean_pct: float
    residual_load_mean_mw: float
    average_price_eur_mwh: float
    peak_price_eur_mwh: float
    net_import_mean_mw: float
    label: str


def _cache_path(data_dir: Path, country: str, start: date, end: date, endpoint: str) -> Path:
    return data_dir / "raw" / f"energy_charts_{country}_{endpoint}_{start.isoformat()}_{end.isoformat()}.json"


def _fetch_endpoint(
    endpoint: str,
    params: dict[str, Any],
    cache_file: Path,
    refresh: bool,
) -> dict[str, Any]:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if cache_file.exists() and not refresh:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    payload = fetch_json_with_retry(f"{ENERGY_CHARTS_URL}/{endpoint}", params)
    cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _slug(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def _canonical_power_name(name: str) -> str:
    normalized = _slug(name)
    if normalized == "load":
        return "load_mw"
    if normalized == "residual_load":
        return "residual_load_mw"
    if normalized == "renewable_share_of_load":
        return "renewable_share_of_load_pct"
    if normalized == "renewable_share_of_generation":
        return "renewable_share_of_generation_pct"
    if normalized == "solar":
        return "solar_generation_mw"
    if normalized == "wind_onshore":
        return "wind_onshore_generation_mw"
    if normalized == "wind_offshore":
        return "wind_offshore_generation_mw"
    return f"generation_{normalized}_mw"


def _power_frame(payload: dict[str, Any]) -> pd.DataFrame:
    timestamps = payload.get("unix_seconds", [])
    frame = pd.DataFrame({"time": pd.to_datetime(timestamps, unit="s", utc=True)})
    for item in payload.get("production_types", []):
        name = str(item.get("name", "unknown"))
        values = item.get("data", [])
        if len(values) == len(frame):
            frame[_canonical_power_name(name)] = pd.to_numeric(pd.Series(values), errors="coerce")
    return frame


def _price_frame(payload: dict[str, Any]) -> pd.DataFrame:
    timestamps = payload.get("unix_seconds", [])
    prices = payload.get("price", [])
    if len(timestamps) != len(prices):
        return pd.DataFrame(columns=["time", "day_ahead_price_eur_mwh"])
    return pd.DataFrame(
        {
            "time": pd.to_datetime(timestamps, unit="s", utc=True),
            "day_ahead_price_eur_mwh": pd.to_numeric(pd.Series(prices), errors="coerce"),
        }
    )


def _flow_frame(payload: dict[str, Any]) -> pd.DataFrame:
    timestamps = payload.get("unix_seconds", [])
    frame = pd.DataFrame({"time": pd.to_datetime(timestamps, unit="s", utc=True)})
    flow_columns: list[str] = []
    for item in payload.get("countries", []):
        values = item.get("data", [])
        if len(values) != len(frame):
            continue
        column = f"flow_{_slug(str(item.get('name', 'unknown')))}_gw"
        frame[column] = pd.to_numeric(pd.Series(values), errors="coerce")
        flow_columns.append(column)
    if flow_columns:
        frame["net_import_mw"] = frame[flow_columns].sum(axis=1, min_count=1) * 1000.0
    return frame


def fetch_energy_charts(
    config: AtlasConfig,
    start: date,
    end: date,
    data_dir: Path | None = None,
    refresh: bool = False,
) -> ElectricityData:
    if not config.electricity.enabled:
        return ElectricityData(pd.DataFrame(), "Energy-Charts", ["Electricity ingestion is disabled."])

    data_dir = data_dir or config.outputs.data_dir
    country = config.electricity.country.lower()
    notes: list[str] = []
    frames: list[pd.DataFrame] = []

    requests_to_make = [
        (
            "public_power",
            {"country": country, "start": start.isoformat(), "end": end.isoformat()},
            _power_frame,
        ),
        (
            "price",
            {
                "bzn": config.electricity.bidding_zone,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            _price_frame,
        ),
        (
            "cbpf",
            {"country": country, "start": start.isoformat(), "end": end.isoformat()},
            _flow_frame,
        ),
    ]
    for endpoint, params, parser in requests_to_make:
        try:
            payload = _fetch_endpoint(
                endpoint,
                params,
                _cache_path(data_dir, country, start, end, endpoint),
                refresh,
            )
            parsed = parser(payload)
            if parsed.empty:
                notes.append(f"Energy-Charts {endpoint} returned no usable values.")
            else:
                frames.append(parsed)
        except Exception as exc:
            notes.append(f"Energy-Charts {endpoint} was unavailable: {exc}")

    if not frames:
        if config.electricity.required:
            raise RuntimeError("Required Energy-Charts data was unavailable. " + " ".join(notes))
        return ElectricityData(pd.DataFrame(), "Energy-Charts / ENTSO-E", notes)

    combined = frames[0]
    for frame in frames[1:]:
        combined = combined.merge(frame, on="time", how="outer")
    combined = combined.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    notes.insert(0, "Hungary-wide electricity context from Energy-Charts (primarily ENTSO-E data).")
    return ElectricityData(combined, "Energy-Charts / ENTSO-E", notes)


def _energy_mwh(frame: pd.DataFrame, column: str) -> float:
    if column not in frame or frame.empty:
        return float("nan")
    times = pd.to_datetime(frame["time"], utc=True)
    intervals = times.diff().dt.total_seconds().div(3600)
    typical = float(intervals[(intervals > 0) & (intervals <= 1.5)].median())
    if not np.isfinite(typical):
        typical = 1.0
    intervals = intervals.fillna(typical).clip(lower=0, upper=1.5)
    values = pd.to_numeric(frame[column], errors="coerce")
    return float((values * intervals).sum(min_count=1))


def _mean(frame: pd.DataFrame, column: str) -> float:
    if column not in frame:
        return float("nan")
    return float(pd.to_numeric(frame[column], errors="coerce").mean())


def _max(frame: pd.DataFrame, column: str) -> float:
    if column not in frame:
        return float("nan")
    return float(pd.to_numeric(frame[column], errors="coerce").max())


def summarize_electricity(frame: pd.DataFrame) -> ElectricitySummary:
    if frame.empty:
        return ElectricitySummary(
            available=False,
            average_load_mw=float("nan"),
            peak_load_mw=float("nan"),
            solar_generation_mwh=float("nan"),
            wind_generation_mwh=float("nan"),
            renewable_share_mean_pct=float("nan"),
            residual_load_mean_mw=float("nan"),
            average_price_eur_mwh=float("nan"),
            peak_price_eur_mwh=float("nan"),
            net_import_mean_mw=float("nan"),
            label="electricity data unavailable",
        )

    solar = _energy_mwh(frame, "solar_generation_mw")
    wind = sum(
        value
        for value in [
            _energy_mwh(frame, "wind_onshore_generation_mw"),
            _energy_mwh(frame, "wind_offshore_generation_mw"),
        ]
        if np.isfinite(value)
    )
    if not any(
        column in frame for column in ["wind_onshore_generation_mw", "wind_offshore_generation_mw"]
    ):
        wind = float("nan")

    renewable_share = _mean(frame, "renewable_share_of_load_pct")
    if not np.isfinite(renewable_share) and "load_mw" in frame:
        generation = pd.Series(0.0, index=frame.index)
        found = False
        for column in ["solar_generation_mw", "wind_onshore_generation_mw", "wind_offshore_generation_mw"]:
            if column in frame:
                generation = generation.add(pd.to_numeric(frame[column], errors="coerce").fillna(0), fill_value=0)
                found = True
        if found:
            load = pd.to_numeric(frame["load_mw"], errors="coerce").replace(0, np.nan)
            renewable_share = float((100 * generation / load).mean())

    if np.isfinite(solar) and np.isfinite(wind):
        if solar >= wind * 1.2:
            label = "solar-led variable renewable output"
        elif wind >= solar * 1.2:
            label = "wind-led variable renewable output"
        else:
            label = "balanced solar and wind output"
    else:
        label = "partial electricity context"

    return ElectricitySummary(
        available=True,
        average_load_mw=_mean(frame, "load_mw"),
        peak_load_mw=_max(frame, "load_mw"),
        solar_generation_mwh=solar,
        wind_generation_mwh=wind,
        renewable_share_mean_pct=renewable_share,
        residual_load_mean_mw=_mean(frame, "residual_load_mw"),
        average_price_eur_mwh=_mean(frame, "day_ahead_price_eur_mwh"),
        peak_price_eur_mwh=_max(frame, "day_ahead_price_eur_mwh"),
        net_import_mean_mw=_mean(frame, "net_import_mw"),
        label=label,
    )
