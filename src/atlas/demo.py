from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from atlas.analogs import AnalogAnalysis, AnalogPeriod
from atlas.anomalies import anomalies_as_frame, compute_anomalies, percentile_rank, period_metrics
from atlas.climatology import ClimateReference
from atlas.config import AtlasConfig, load_config
from atlas.dates import last_complete_period
from atlas.electricity import summarize_electricity
from atlas.energy import compute_energy_index, compute_physical_energy
from atlas.fronts import detect_fronts
from atlas.hungaromet import LightningArchive, RadarArchive, StationObservations
from atlas.land import analyze_land_surface
from atlas.phenomena import detect_weather_phenomena
from atlas.plots import generate_all_figures
from atlas.profile import ModelProfile
from atlas.regimes import classify_period
from atlas.satellite import SatelliteArchive, SatelliteFrame
from atlas.serialization import json_ready
from atlas.site import build_site
from atlas.synoptic import SynopticArchive


DEMO_NOTICE = (
    "Demonstration edition: all weather, electricity and imagery values are "
    "deterministic synthetic data generated for layout testing."
)


def _weather_frame(
    start: date,
    end: date,
    timezone_name: str,
    event_time: pd.Timestamp,
) -> pd.DataFrame:
    local_time = pd.date_range(
        pd.Timestamp(start, tz=timezone_name),
        pd.Timestamp(end + timedelta(days=1), tz=timezone_name),
        inclusive="left",
        freq="h",
    )
    utc_time = local_time.tz_convert("UTC")
    hour = local_time.hour.to_numpy(dtype=float)
    elapsed = (utc_time - event_time).total_seconds().to_numpy(dtype=float) / 3600.0
    diurnal = np.sin(2.0 * np.pi * (hour - 8.0) / 24.0)
    storm = np.exp(-((elapsed / 6.0) ** 2))
    frontal_step = 0.5 * (1.0 + np.tanh(elapsed / 2.5))

    temperature = 24.0 + 7.0 * diurnal - 4.0 * frontal_step
    dew_point = 15.0 + 1.6 * np.sin(2.0 * np.pi * (hour - 4.0) / 24.0) + 2.8 * storm
    relative_humidity = np.clip(
        100.0 * np.exp((17.625 * dew_point / (243.04 + dew_point)) - (17.625 * temperature / (243.04 + temperature))),
        30.0,
        100.0,
    )
    cloud = np.clip(22.0 + 72.0 * storm + 10.0 * np.cos(2.0 * np.pi * hour / 24.0), 5.0, 100.0)
    solar_shape = np.clip(np.sin(np.pi * (hour - 5.0) / 15.0), 0.0, None)
    shortwave = 870.0 * solar_shape * np.clip(1.0 - 0.72 * cloud / 100.0, 0.18, 1.0)
    precipitation = 6.4 * np.exp(-((elapsed - 0.5) / 1.25) ** 2)
    precipitation[precipitation < 0.08] = 0.0
    pressure = 1017.5 - 9.5 * storm + 1.2 * np.sin(2.0 * np.pi * elapsed / 30.0)
    wind_10m = 2.4 + 6.8 * storm + 0.8 * np.sin(2.0 * np.pi * (hour - 10.0) / 24.0) ** 2
    wind_100m = wind_10m * 1.48 + 0.6
    wind_direction = (145.0 + 175.0 * frontal_step + 14.0 * np.sin(elapsed / 5.0)) % 360.0
    gust = wind_10m + 2.5 + 7.0 * storm
    saturation_kpa = 0.6108 * np.exp(17.27 * temperature / (temperature + 237.3))
    vpd = saturation_kpa * (1.0 - relative_humidity / 100.0)
    et0 = np.clip(shortwave / 1000.0 * (0.34 + 0.025 * np.maximum(temperature - 15.0, 0.0)), 0.0, None)

    slow_phase = np.arange(len(local_time), dtype=float) / 24.0
    frame = pd.DataFrame(
        {
            "time": utc_time,
            "local_time": local_time,
            "temperature_2m": temperature,
            "dew_point_2m": dew_point,
            "relative_humidity_2m": relative_humidity,
            "precipitation": precipitation,
            "rain": precipitation,
            "snowfall": np.zeros(len(local_time)),
            "cloud_cover": cloud,
            "pressure_msl": pressure,
            "wind_speed_10m": wind_10m,
            "wind_speed_100m": wind_100m,
            "wind_direction_10m": wind_direction,
            "wind_gusts_10m": gust,
            "shortwave_radiation": shortwave,
            "direct_radiation": shortwave * 0.69,
            "diffuse_radiation": shortwave * 0.31,
            "sunshine_duration": np.where(shortwave >= 120.0, 3600.0, 0.0),
            "vapour_pressure_deficit": vpd,
            "et0_fao_evapotranspiration": et0,
            "soil_temperature_0_to_7cm": 21.5 + 3.1 * diurnal,
            "soil_temperature_7_to_28cm": 20.8 + 1.4 * np.sin(2.0 * np.pi * (hour - 11.0) / 24.0),
            "soil_temperature_28_to_100cm": 19.4 + 0.45 * np.sin(2.0 * np.pi * slow_phase / 14.0),
            "soil_temperature_100_to_255cm": 16.8 + 0.18 * np.sin(2.0 * np.pi * slow_phase / 45.0),
            "soil_moisture_0_to_7cm": np.clip(0.19 + 0.055 * storm - 0.00022 * slow_phase, 0.12, 0.34),
            "soil_moisture_7_to_28cm": np.clip(0.23 + 0.025 * storm - 0.00010 * slow_phase, 0.16, 0.35),
            "soil_moisture_28_to_100cm": np.clip(0.27 - 0.00004 * slow_phase, 0.20, 0.34),
            "soil_moisture_100_to_255cm": 0.31 + 0.003 * np.sin(2.0 * np.pi * slow_phase / 60.0),
        }
    )
    return frame


def _climate_table(days: int, years: range, recent: bool = False) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for year in years:
        cycle = np.sin((year - 1940) * 1.73)
        secondary = np.cos((year - 1940) * 0.91)
        rows.append(
            {
                "baseline_year": year,
                "temperature_mean_c": 22.1 + (0.65 if recent else 0.0) + 1.15 * cycle,
                "precipitation_total_mm": days * (2.7 + 1.35 * secondary),
                "wind_speed_mean_ms": 4.1 + 0.48 * cycle,
                "pressure_mean_hpa": 1015.0 + 2.6 * secondary,
                "cloud_cover_mean_pct": 45.0 + 7.8 * cycle,
                "shortwave_total_wh_m2": days * (5350.0 + 520.0 * secondary),
                "et0_total_mm": days * (4.25 + 0.35 * cycle),
                "water_balance_mm": days * (-1.55 + 1.25 * secondary),
            }
        )
    return pd.DataFrame(rows)


def _climate_reference(metrics: dict[str, float], days: int) -> ClimateReference:
    standard = _climate_table(days, range(1991, 2021))
    recent = _climate_table(days, range(2016, 2026), recent=True)
    full = _climate_table(days, range(1990, 2026))
    standard_anomalies = compute_anomalies(metrics, standard)
    recent_anomalies = compute_anomalies(metrics, recent)
    percentiles = {
        item.metric: percentile_rank(metrics[item.metric], full[item.metric])
        for item in standard_anomalies
    }
    return ClimateReference(
        standard,
        recent,
        full,
        standard_anomalies,
        recent_anomalies,
        percentiles,
        [
            "Synthetic reference distributions preserve the Atlas 1991-2020, recent-decade and full-record comparison structure.",
            DEMO_NOTICE,
        ],
    )


def _station(weather: pd.DataFrame) -> StationObservations:
    frame = pd.DataFrame(
        {
            "time": weather["time"],
            "temperature_c": weather["temperature_2m"] + 0.25,
            "dew_point_c": weather["dew_point_2m"] + 0.1,
            "relative_humidity_pct": weather["relative_humidity_2m"],
            "pressure_msl_hpa": weather["pressure_msl"] - 0.35,
            "wind_speed_ms": weather["wind_speed_10m"] * 0.92,
            "wind_direction_deg": weather["wind_direction_10m"],
            "wind_gust_ms": weather["wind_gusts_10m"] * 1.04,
            "precipitation_mm": weather["precipitation"],
            "visibility_m": np.where(weather["relative_humidity_2m"] >= 94.0, 4200.0, 18000.0),
        }
    )
    return StationObservations(
        frame,
        64711,
        "Debrecen Airport",
        ["Synthetic station series shaped like an hourly Debrecen Airport record."],
    )


def _radar_and_lightning(
    weather: pd.DataFrame,
    event_time: pd.Timestamp,
    config: AtlasConfig,
) -> tuple[RadarArchive, LightningArchive]:
    times = list(pd.date_range(event_time - pd.Timedelta(hours=18), event_time + pd.Timedelta(hours=18), freq="3h"))
    latitudes = np.linspace(46.4, 48.7, 39)
    longitudes = np.linspace(20.0, 23.4, 49)
    longitude_grid, latitude_grid = np.meshgrid(longitudes, latitudes)
    fields = []
    for index, timestamp in enumerate(times):
        progress = index / max(len(times) - 1, 1)
        center_lon = 20.4 + 2.7 * progress
        center_lat = 47.9 - 0.55 * progress
        strength = 18.0 + 43.0 * np.exp(-((index - len(times) / 2.0) / 2.8) ** 2)
        cell = strength * np.exp(-(((longitude_grid - center_lon) / 0.38) ** 2 + ((latitude_grid - center_lat) / 0.28) ** 2))
        secondary = 24.0 * np.exp(-(((longitude_grid - center_lon - 0.55) / 0.30) ** 2 + ((latitude_grid - center_lat + 0.38) / 0.24) ** 2))
        fields.append(np.clip(cell + secondary, 0.0, 65.0))
    reflectivity = np.asarray(fields)
    accumulation = np.sum(np.clip((reflectivity - 18.0) / 9.0, 0.0, None), axis=0) * 0.45
    debrecen_lat = int(np.abs(latitudes - config.location.latitude).argmin())
    debrecen_lon = int(np.abs(longitudes - config.location.longitude).argmin())
    timeline = pd.DataFrame(
        {
            "time": times,
            "domain_max_dbz": np.nanmax(reflectivity, axis=(1, 2)),
            "reflectivity_dbz": reflectivity[:, debrecen_lat, debrecen_lon],
        }
    )
    radar = RadarArchive(
        times,
        latitudes,
        longitudes,
        reflectivity,
        accumulation,
        timeline,
        ["Synthetic migrating convective line for replay and accumulation layout testing."],
    )

    rng = np.random.default_rng(20260802)
    count = 38
    angles = rng.uniform(0.0, 2.0 * np.pi, count)
    distances = rng.uniform(18.0, 142.0, count)
    event_times = event_time + pd.to_timedelta(rng.normal(0.0, 3.2, count), unit="h")
    lightning_frame = pd.DataFrame(
        {
            "time": event_times,
            "latitude": config.location.latitude + distances / 111.0 * np.cos(angles),
            "longitude": config.location.longitude + distances / (111.0 * np.cos(np.radians(config.location.latitude))) * np.sin(angles),
            "peak_current_ka": rng.normal(-7.0, 24.0, count),
            "distance_km": distances,
        }
    ).sort_values("time")
    hourly = (
        lightning_frame.assign(time=pd.to_datetime(lightning_frame["time"], utc=True).dt.floor("h"))
        .groupby("time")
        .size()
        .rename("flash_count")
        .reset_index()
    )
    lightning = LightningArchive(
        lightning_frame,
        hourly,
        ["Synthetic lightning events spatially distributed around Debrecen."],
    )
    return radar, lightning


def _satellite(
    output_dir: Path,
    event_time: pd.Timestamp,
) -> SatelliteArchive:
    source_dir = output_dir / "satellite_sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    products = ["AirmassRGB", "NaturalRGB", "NightRGB", "FogRGB", "InfraCloud"]
    palettes = {
        "AirmassRGB": ((36, 61, 118), (202, 68, 124)),
        "NaturalRGB": ((31, 91, 77), (208, 208, 186)),
        "NightRGB": ((45, 34, 67), (189, 129, 78)),
        "FogRGB": ((45, 80, 106), (204, 226, 219)),
        "InfraCloud": ((28, 31, 41), (232, 229, 219)),
    }
    archive: dict[str, list[SatelliteFrame]] = {}
    width, height = 720, 420
    x = np.linspace(0.0, 1.0, width)[None, :]
    y = np.linspace(0.0, 1.0, height)[:, None]
    for product_index, product in enumerate(products):
        frames: list[SatelliteFrame] = []
        start_color, end_color = palettes[product]
        for frame_index, timestamp in enumerate(pd.date_range(event_time - pd.Timedelta(hours=18), periods=5, freq="9h")):
            wave = 0.5 + 0.5 * np.sin(8.0 * x + 5.0 * y + frame_index * 0.9 + product_index)
            plume = np.exp(-(((x - (0.22 + frame_index * 0.14)) / 0.22) ** 2 + ((y - 0.53) / 0.28) ** 2))
            mix = np.clip(0.42 * wave + 0.58 * plume, 0.0, 1.0)
            rgb = np.empty((height, width, 3), dtype=np.uint8)
            for channel in range(3):
                rgb[:, :, channel] = start_color[channel] + mix * (end_color[channel] - start_color[channel])
            image = Image.fromarray(rgb, mode="RGB")
            draw = ImageDraw.Draw(image)
            draw.rectangle((14, 14, 288, 64), fill=(0, 0, 0, 180))
            draw.text((26, 24), f"SYNTHETIC {product}", fill=(255, 255, 255))
            draw.text((26, 43), timestamp.strftime("%Y-%m-%d %H:%M UTC"), fill=(230, 236, 244))
            path = source_dir / f"{product}_{timestamp.strftime('%Y%m%d_%H%M')}.png"
            image.save(path)
            frames.append(SatelliteFrame(timestamp, product, path))
        archive[product] = frames
    return SatelliteArchive(
        archive,
        ["Synthetic Meteosat-style image sequence for player and synchronization testing."],
    )


def _model_profile(weather: pd.DataFrame, event_time: pd.Timestamp) -> ModelProfile:
    levels = np.array([1000, 950, 925, 850, 800, 700, 600, 500, 400, 300, 250, 200], dtype=float)
    heights = np.array([120, 540, 780, 1480, 1960, 3060, 4250, 5650, 7200, 9250, 10450, 11850], dtype=float)
    profile_times = pd.DatetimeIndex(pd.to_datetime(weather["time"], utc=True))[::3]
    rows: list[dict[str, object]] = []
    for time_index, timestamp in enumerate(profile_times):
        surface_temperature = float(weather.loc[weather["time"] == timestamp, "temperature_2m"].iloc[0])
        for level, height in zip(levels, heights):
            temperature = surface_temperature - 6.2 * height / 1000.0 + 1.8 * np.sin(height / 2400.0 + time_index / 5.0)
            moisture_bulge = 5.5 * np.exp(-((height - 3000.0) / 1700.0) ** 2)
            dew_point = temperature - (5.0 + height / 2300.0) + moisture_bulge
            rh = np.clip(92.0 - (temperature - dew_point) * 7.0, 12.0, 98.0)
            rows.append(
                {
                    "time": timestamp,
                    "pressure_hpa": level,
                    "temperature_c": temperature,
                    "dew_point_c": dew_point,
                    "relative_humidity_pct": rh,
                    "geopotential_height_m": height,
                    "wind_speed_ms": 4.0 + height / 520.0 + 2.0 * np.sin(time_index / 4.0),
                    "wind_direction_deg": (150.0 + height / 48.0 + time_index * 3.0) % 360.0,
                }
            )
    series = pd.DataFrame(rows)
    valid_time = min(profile_times, key=lambda timestamp: abs(timestamp - event_time))
    selected = series[series["time"] == valid_time].drop(columns="time").reset_index(drop=True)
    elapsed = (pd.DatetimeIndex(pd.to_datetime(weather["time"], utc=True)) - event_time).total_seconds() / 3600.0
    instability = np.exp(-((np.asarray(elapsed) / 7.0) ** 2))
    surface = pd.DataFrame(
        {
            "time": weather["time"],
            "cape": 80.0 + 1380.0 * instability,
            "convective_inhibition": -95.0 + 80.0 * instability,
            "boundary_layer_height": 450.0 + 1950.0 * np.clip(np.sin(np.pi * (weather["local_time"].dt.hour - 6.0) / 14.0), 0.0, None),
            "total_column_integrated_water_vapour": 22.0 + 11.0 * instability,
            "freezing_level_height": 3650.0 + 450.0 * np.sin(2.0 * np.pi * weather["local_time"].dt.hour / 24.0),
            "wet_bulb_temperature_2m": weather["temperature_2m"] - 0.32 * (100.0 - weather["relative_humidity_2m"]),
        }
    )
    diagnostics = {
        "surface_based_cape_j_kg": 1460.0,
        "surface_based_cin_j_kg": -18.0,
        "lcl_height_m_asl": 1080.0,
        "lfc_height_m_asl": 1560.0,
        "equilibrium_level_m_asl": 10450.0,
        "precipitable_water_mm": 32.5,
        "k_index": 31.0,
        "total_totals_index": 47.0,
        "wet_bulb_zero_m_asl": 3380.0,
        "boundary_layer_height_m": 2120.0,
        "ventilation_index_m2_s": 19400.0,
        "freezing_level_m_asl": 3950.0,
    }
    return ModelProfile(
        selected,
        valid_time,
        "Atlas deterministic demonstration profile",
        diagnostics,
        ["Synthetic thermodynamic and wind profile for advanced-panel layout testing."],
        series,
        surface,
    )


def _synoptic(event_time: pd.Timestamp, config: AtlasConfig) -> SynopticArchive:
    times = list(pd.date_range(event_time - pd.Timedelta(hours=24), event_time + pd.Timedelta(hours=24), freq="6h"))
    latitudes = np.arange(config.synoptic.latitude_min, config.synoptic.latitude_max + 0.1, 0.5)
    longitudes = np.arange(config.synoptic.longitude_min, config.synoptic.longitude_max + 0.1, 0.5)
    lon, lat = np.meshgrid(longitudes, latitudes)
    fields: dict[str, list[np.ndarray]] = {name: [] for name in [
        "pressure", "h500", "h300", "t850", "u850", "v850", "jet", "vort",
        "rh700", "omega700", "thetae", "advection", "frontogenesis",
    ]}
    for index, _ in enumerate(times):
        phase = index * 0.62
        trough = np.sin((lon - 20.5) * 0.55 + phase) + 0.45 * np.cos((lat - 47.5) * 0.8)
        fields["pressure"].append(1014.0 + 5.2 * trough - 0.7 * (lat - 47.5))
        fields["h500"].append(5680.0 + 82.0 * trough + 18.0 * (lat - 47.5))
        fields["h300"].append(9320.0 + 115.0 * trough + 24.0 * (lat - 47.5))
        fields["t850"].append(15.0 - 1.05 * (lat - 47.5) + 3.1 * np.sin((lon - 19.0) * 0.45 + phase))
        fields["u850"].append(5.0 + 3.0 * np.cos((lat - 47.0) * 0.7 + phase))
        fields["v850"].append(2.5 + 3.5 * np.sin((lon - 20.0) * 0.55 + phase))
        fields["jet"].append(24.0 + 35.0 * np.exp(-((lat - 48.8 - 0.25 * np.sin(phase)) / 1.05) ** 2))
        fields["vort"].append(8.0 * np.sin((lon - 20.0) * 0.75 + phase) * np.cos((lat - 47.0) * 0.65))
        fields["rh700"].append(np.clip(48.0 + 42.0 * np.sin((lon + lat) * 0.42 + phase), 8.0, 100.0))
        fields["omega700"].append(0.18 * np.sin((lon - 20.0) * 0.7 + phase) * np.cos((lat - 47.0) * 0.7))
        fields["thetae"].append(318.0 + 8.0 * np.sin((lon - 18.0) * 0.55 + phase) - 2.0 * (lat - 47.0))
        fields["advection"].append(1.9 * np.cos((lon - 20.0) * 0.8 + phase) * np.sin((lat - 47.0) * 0.7))
        fields["frontogenesis"].append(3.4 * np.exp(-((lon - 20.0 - 0.35 * index) / 0.75) ** 2) * np.exp(-((lat - 47.3) / 1.4) ** 2))
    arrays = {name: np.asarray(value) for name, value in fields.items()}
    return SynopticArchive(
        times,
        latitudes,
        longitudes,
        arrays["pressure"],
        arrays["h500"],
        arrays["h300"],
        arrays["t850"],
        arrays["u850"],
        arrays["v850"],
        arrays["jet"],
        arrays["vort"],
        arrays["rh700"],
        arrays["omega700"],
        arrays["thetae"],
        arrays["advection"],
        arrays["frontogenesis"],
        ["Synthetic Central European fields exercise every selectable synoptic layer."],
    )


def _electricity(weather: pd.DataFrame) -> pd.DataFrame:
    hour = weather["local_time"].dt.hour.to_numpy(dtype=float)
    load = 4700.0 + 720.0 * np.sin(2.0 * np.pi * (hour - 9.0) / 24.0) ** 2 + 180.0 * (weather["temperature_2m"].to_numpy() - 23.0)
    solar = np.clip(weather["shortwave_radiation"].to_numpy() * 3.25, 0.0, 2850.0)
    wind = np.clip(10.0 * weather["wind_speed_100m"].to_numpy() ** 2.15, 50.0, 1750.0)
    residual = load - solar - wind
    price = 46.0 + 0.012 * residual + 18.0 * np.sin(2.0 * np.pi * (hour - 15.0) / 24.0) ** 2
    return pd.DataFrame(
        {
            "time": weather["time"],
            "load_mw": load,
            "residual_load_mw": residual,
            "solar_generation_mw": solar,
            "wind_onshore_generation_mw": wind,
            "day_ahead_price_eur_mwh": price,
            "net_import_mw": 550.0 + 0.20 * residual,
            "renewable_share_of_load_pct": np.clip(100.0 * (solar + wind) / load, 0.0, 100.0),
        }
    )


def _analogs(start: date, end: date) -> AnalogAnalysis:
    matches = [
        AnalogPeriod("2017-07-18", "2017-07-20", 0.91, 0.42, "warm, convective transition", {"temperature_mean_c": 23.8, "precipitation_total_mm": 18.6}),
        AnalogPeriod("2009-07-24", "2009-07-26", 0.87, 0.57, "humid frontal passage", {"temperature_mean_c": 22.9, "precipitation_total_mm": 22.1}),
        AnalogPeriod("1998-08-02", "1998-08-04", 0.83, 0.69, "bright start, stormy finish", {"temperature_mean_c": 23.4, "precipitation_total_mm": 14.8}),
        AnalogPeriod("2013-07-29", "2013-07-31", 0.79, 0.81, "wind shift after heat", {"temperature_mean_c": 24.6, "precipitation_total_mm": 11.2}),
        AnalogPeriod("1987-07-15", "1987-07-17", 0.76, 0.93, "mixed summer regime", {"temperature_mean_c": 22.5, "precipitation_total_mm": 9.4}),
    ]
    archive = pd.DataFrame([asdict(match) for match in matches])
    return AnalogAnalysis(matches, archive, [f"Synthetic analog ranking for the {start} to {end} demonstration period."])


def _write_csv(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def run_demo_pipeline(
    config_path: str | Path = "configs/atlas.yml",
    today: date | None = None,
) -> Path:
    config = load_config(config_path)
    start, end = last_complete_period(
        today=today,
        tz_name=config.location.timezone,
        days=config.reporting.window_days,
    )
    event_time = pd.Timestamp(end, tz=config.location.timezone).tz_convert("UTC") - pd.Timedelta(hours=10)
    context_start = end - timedelta(days=config.reporting.context_days - 1)
    land_start = end - timedelta(days=config.land_surface.context_days - 1)
    context = _weather_frame(context_start, end, config.location.timezone, event_time)
    current = context[context["local_time"].dt.date >= start].reset_index(drop=True)
    daily = current[current["local_time"].dt.date == end].reset_index(drop=True)
    land_frame = _weather_frame(land_start, end, config.location.timezone, event_time)

    current_metrics = period_metrics(current)
    daily_metrics = period_metrics(daily)
    climate = _climate_reference(current_metrics, config.reporting.window_days)
    daily_climate = _climate_reference(daily_metrics, 1)
    baseline_means = {
        column: float(pd.to_numeric(climate.recent_table[column], errors="coerce").mean())
        for column in climate.recent_table.columns
        if column != "baseline_year"
    }
    energy = compute_energy_index(current_metrics, baseline_means)
    daily_baseline = {
        column: float(pd.to_numeric(daily_climate.recent_table[column], errors="coerce").mean())
        for column in daily_climate.recent_table.columns
        if column != "baseline_year"
    }
    daily_energy = compute_energy_index(daily_metrics, daily_baseline)
    physical_energy = compute_physical_energy(config, current)
    daily_physical_energy = compute_physical_energy(config, daily)
    regime = classify_period(current, climate.standard_anomalies)
    daily_regime = classify_period(daily, daily_climate.standard_anomalies)

    station = _station(current)
    fronts = detect_fronts(station.frame)
    radar, lightning = _radar_and_lightning(current, event_time, config)
    processed_dir = config.outputs.data_dir / "processed" / "demo"
    figures_dir = config.outputs.reports_dir / "figures" / "demo"
    for target in [processed_dir, figures_dir]:
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
    satellite = _satellite(processed_dir, event_time)
    profile = _model_profile(current, event_time)
    synoptic = _synoptic(event_time, config)
    phenomena = detect_weather_phenomena(
        current,
        station,
        radar,
        lightning,
        fronts,
        profile,
        config.location.timezone,
    )
    balance_samples = {
        7: pd.Series(np.linspace(-42.0, 38.0, 81)),
        30: pd.Series(np.linspace(-145.0, 95.0, 121)),
        90: pd.Series(np.linspace(-310.0, 180.0, 141)),
    }
    land = analyze_land_surface(land_frame, balance_samples, config.location.timezone)
    electricity = _electricity(current)
    electricity_summary = summarize_electricity(electricity)
    analogs = _analogs(start, end)

    figure_paths = generate_all_figures(
        frame=current,
        context_frame=context,
        climate=climate,
        daily_climate=daily_climate,
        land=land,
        phenomena=phenomena,
        daily_frame=daily,
        anomalies=climate.standard_anomalies,
        energy=energy,
        electricity=electricity,
        electricity_summary=electricity_summary,
        profile=profile,
        station=station,
        radar=radar,
        lightning=lightning,
        satellite=satellite,
        fronts=fronts,
        synoptic=synoptic,
        physical_energy=physical_energy,
        daily_physical_energy=daily_physical_energy,
        regime=regime,
        current_start=start,
        output_dir=figures_dir,
        config=config,
    )

    processed_paths: dict[str, Path] = {
        "current_hourly": _write_csv(processed_dir / "demo_current_hourly.csv", current),
        "seven_day_context_hourly": _write_csv(processed_dir / "demo_seven_day_context.csv", context),
        "period_metrics": _write_csv(processed_dir / "demo_period_metrics.csv", pd.DataFrame([current_metrics])),
        "baseline_metrics": _write_csv(processed_dir / "demo_recent_baseline.csv", climate.recent_table),
        "standard_normal_metrics": _write_csv(processed_dir / "demo_1991_2020_normal.csv", climate.standard_table),
        "full_record_metrics": _write_csv(processed_dir / "demo_full_record.csv", climate.full_record_table),
        "anomalies": _write_csv(processed_dir / "demo_standard_anomalies.csv", anomalies_as_frame(climate.standard_anomalies)),
        "recent_anomalies": _write_csv(processed_dir / "demo_recent_anomalies.csv", anomalies_as_frame(climate.recent_anomalies)),
        "electricity": _write_csv(processed_dir / "demo_electricity.csv", electricity),
        "model_profile": _write_csv(processed_dir / "demo_model_profile.csv", profile.frame),
        "model_profile_series": _write_csv(processed_dir / "demo_model_profile_series.csv", profile.series),
        "model_profile_surface": _write_csv(processed_dir / "demo_model_profile_surface.csv", profile.surface_series),
        "hungaromet_station": _write_csv(processed_dir / "demo_station.csv", station.frame),
        "radar_timeline": _write_csv(processed_dir / "demo_radar_timeline.csv", radar.timeline),
        "lightning": _write_csv(processed_dir / "demo_lightning.csv", lightning.frame),
        "frontal_passages": _write_csv(processed_dir / "demo_fronts.csv", pd.DataFrame([asdict(item) for item in fronts.events])),
        "phenomena": _write_csv(processed_dir / "demo_phenomena.csv", pd.DataFrame([asdict(item) for item in phenomena.events])),
        "historical_analogs": _write_csv(processed_dir / "demo_analogs.csv", analogs.archive),
        "physical_energy": _write_csv(processed_dir / "demo_physical_energy.csv", physical_energy.series),
        "daily_physical_energy": _write_csv(processed_dir / "demo_daily_physical_energy.csv", daily_physical_energy.series),
        "land_surface_hourly": _write_csv(processed_dir / "demo_land_hourly.csv", land.hourly),
        "land_surface_daily": _write_csv(processed_dir / "demo_land_daily.csv", land.daily),
    }
    radar_path = processed_dir / "demo_radar_accumulation.npz"
    np.savez_compressed(radar_path, latitude=radar.latitudes, longitude=radar.longitudes, accumulation_mm=radar.accumulation_mm)
    processed_paths["radar_accumulation"] = radar_path
    synoptic_path = processed_dir / "demo_synoptic_fields.npz"
    np.savez_compressed(
        synoptic_path,
        time=np.array([timestamp.isoformat() for timestamp in synoptic.times]),
        latitude=synoptic.latitudes,
        longitude=synoptic.longitudes,
        pressure_msl_hpa=synoptic.pressure_msl_hpa,
        height_500m=synoptic.height_500m,
        wind_speed_300ms=synoptic.wind_speed_300ms,
        vorticity_500_1e5_s=synoptic.vorticity_500_1e5_s,
        relative_humidity_700pct=synoptic.relative_humidity_700pct,
        theta_e_850k=synoptic.theta_e_850k,
        frontogenesis_850k_100km_3h=synoptic.frontogenesis_850k_100km_3h,
    )
    processed_paths["synoptic_fields"] = synoptic_path
    satellite_manifest = processed_dir / "demo_satellite_manifest.json"
    satellite_manifest.write_text(
        json.dumps(
            {
                product: [
                    {"time": frame.time.isoformat(), "path": str(frame.path)}
                    for frame in frames
                ]
                for product, frames in satellite.frames.items()
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    processed_paths["satellite_manifest"] = satellite_manifest
    source_summary = processed_dir / "demo_summary.json"
    source_summary.write_text(
        json.dumps(
            json_ready(
                {
                    "demo": True,
                    "period_start": start,
                    "period_end": end,
                    "regime": asdict(regime),
                    "electricity": asdict(electricity_summary),
                }
            ),
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    processed_paths["summary"] = source_summary

    return build_site(
        config=config,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        daily_date=end.isoformat(),
        current_metrics=current_metrics,
        daily_metrics=daily_metrics,
        baseline_metrics=baseline_means,
        anomalies=climate.standard_anomalies,
        climate_reference=climate,
        daily_climate_reference=daily_climate,
        energy=energy,
        daily_energy=daily_energy,
        electricity=electricity_summary,
        electricity_notes=["Synthetic Hungary electricity series for layout testing."],
        profile=profile,
        station=station,
        radar=radar,
        lightning=lightning,
        satellite=satellite,
        fronts=fronts,
        phenomena=phenomena,
        analogs=analogs,
        synoptic=synoptic,
        land=land,
        physical_energy=physical_energy,
        daily_physical_energy=daily_physical_energy,
        regime=regime,
        daily_regime=daily_regime,
        figure_paths=figure_paths,
        processed_paths=processed_paths,
        site_dir=config.outputs.site_dir,
        quality_notes=[DEMO_NOTICE],
        edition_notice=DEMO_NOTICE,
    )
