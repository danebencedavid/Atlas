from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pvlib

from atlas.config import AtlasConfig


@dataclass(frozen=True)
class EnergyIndex:
    solar_index: float
    wind_index: float
    combined_score: float
    calm_wind_penalty: float
    cloud_penalty: float
    label: str


@dataclass(frozen=True)
class PhysicalEnergy:
    series: pd.DataFrame
    pv_yield_kwh_per_kwp: float
    pv_capacity_factor_pct: float
    wind_full_load_hours: float
    wind_capacity_factor_pct: float
    mean_wind_power_density_w_m2: float
    peak_pv_time: str | None
    peak_wind_time: str | None
    notes: list[str]


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    if not np.isfinite(value):
        return 50.0
    return float(min(max(value, lower), upper))


def ratio_index(value: float, baseline: float) -> float:
    if not np.isfinite(value) or not np.isfinite(baseline) or baseline <= 0:
        return 50.0
    return clamp(100.0 * value / baseline)


def compute_energy_index(current: dict[str, float], baseline: dict[str, float]) -> EnergyIndex:
    solar_raw = ratio_index(current["shortwave_total_wh_m2"], baseline["shortwave_total_wh_m2"])
    cloud_excess = max(current["cloud_cover_mean_pct"] - baseline["cloud_cover_mean_pct"], 0.0)
    cloud_penalty = clamp(cloud_excess * 0.35, 0.0, 30.0)
    solar_index = clamp(solar_raw - cloud_penalty)

    wind_ratio = ratio_index(current["wind_speed_mean_ms"] ** 3, baseline["wind_speed_mean_ms"] ** 3)
    calm_wind_penalty = clamp(max(3.0 - current["wind_speed_mean_ms"], 0.0) * 12.0, 0.0, 36.0)
    wind_index = clamp(wind_ratio - calm_wind_penalty)

    combined = clamp((solar_index + wind_index) / 2.0)
    if solar_index >= wind_index + 10:
        label = "solar-favored"
    elif wind_index >= solar_index + 10:
        label = "wind-favored"
    else:
        label = "balanced renewable"

    return EnergyIndex(
        solar_index=round(solar_index, 1),
        wind_index=round(wind_index, 1),
        combined_score=round(combined, 1),
        calm_wind_penalty=round(calm_wind_penalty, 1),
        cloud_penalty=round(cloud_penalty, 1),
        label=label,
    )


def _air_density(frame: pd.DataFrame) -> np.ndarray:
    temperature_c = pd.to_numeric(frame["temperature_2m"], errors="coerce").to_numpy(dtype=float)
    pressure_hpa = pd.to_numeric(frame["pressure_msl"], errors="coerce").to_numpy(dtype=float)
    humidity = pd.to_numeric(frame["relative_humidity_2m"], errors="coerce").to_numpy(dtype=float)
    kelvin = temperature_c + 273.15
    saturation_hpa = 6.112 * np.exp(17.67 * temperature_c / (temperature_c + 243.5))
    vapor_hpa = saturation_hpa * np.clip(humidity, 0.0, 100.0) / 100.0
    dry_hpa = pressure_hpa - vapor_hpa
    return dry_hpa * 100.0 / (287.05 * kelvin) + vapor_hpa * 100.0 / (461.5 * kelvin)


def compute_physical_energy(config: AtlasConfig, frame: pd.DataFrame) -> PhysicalEnergy:
    if frame.empty:
        return PhysicalEnergy(pd.DataFrame(), *(float("nan"),) * 5, None, None, ["Weather data unavailable."])
    times = pd.DatetimeIndex(pd.to_datetime(frame["time"], utc=True))
    weather = frame.copy().reset_index(drop=True)
    solar_position = pvlib.solarposition.get_solarposition(
        times, config.location.latitude, config.location.longitude
    )
    zenith = solar_position["apparent_zenith"].to_numpy(dtype=float)
    azimuth = solar_position["azimuth"].to_numpy(dtype=float)
    cosine_zenith = np.clip(np.cos(np.radians(zenith)), 0.0, None)
    ghi = pd.to_numeric(weather["shortwave_radiation"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    dhi = pd.to_numeric(weather["diffuse_radiation"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    direct_horizontal = pd.to_numeric(weather["direct_radiation"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    dni = np.divide(
        direct_horizontal,
        cosine_zenith,
        out=np.zeros_like(direct_horizontal),
        where=cosine_zenith > 0.065,
    )
    dni = np.clip(dni, 0.0, 1200.0)
    irradiance = pvlib.irradiance.get_total_irradiance(
        surface_tilt=config.physical_energy.pv_tilt_degrees,
        surface_azimuth=config.physical_energy.pv_azimuth_degrees,
        solar_zenith=zenith,
        solar_azimuth=azimuth,
        dni=dni,
        ghi=ghi,
        dhi=dhi,
        albedo=0.2,
    )
    poa = np.nan_to_num(
        np.asarray(irradiance["poa_global"], dtype=float), nan=0.0, posinf=0.0, neginf=0.0
    )
    air_temperature = pd.to_numeric(weather["temperature_2m"], errors="coerce").to_numpy(dtype=float)
    wind_10m = pd.to_numeric(weather["wind_speed_10m"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    cell_temperature = np.asarray(
        pvlib.temperature.faiman(poa, air_temperature, wind_10m), dtype=float
    )
    pv_kw_per_kwp = np.clip(
        poa / 1000.0
        * (1.0 + config.physical_energy.pv_temperature_coefficient * (cell_temperature - 25.0))
        * 0.96,
        0.0,
        1.2,
    )

    density = _air_density(weather)
    wind_speed = pd.to_numeric(weather["wind_speed_100m"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    density_corrected_speed = wind_speed * np.power(np.clip(density / 1.225, 0.5, 1.5), 1.0 / 3.0)
    cut_in = config.physical_energy.wind_cut_in_ms
    rated = config.physical_energy.wind_rated_ms
    cut_out = config.physical_energy.wind_cut_out_ms
    wind_capacity = np.zeros_like(density_corrected_speed)
    partial = (density_corrected_speed >= cut_in) & (density_corrected_speed < rated)
    wind_capacity[partial] = (
        density_corrected_speed[partial] ** 3 - cut_in**3
    ) / (rated**3 - cut_in**3)
    wind_capacity[(density_corrected_speed >= rated) & (density_corrected_speed < cut_out)] = 1.0
    wind_power_density = 0.5 * density * wind_speed**3

    series = pd.DataFrame(
        {
            "time": times,
            "poa_irradiance_w_m2": poa,
            "pv_power_kw_per_kwp": pv_kw_per_kwp,
            "pv_cell_temperature_c": cell_temperature,
            "air_density_kg_m3": density,
            "hub_wind_speed_ms": wind_speed,
            "density_corrected_wind_ms": density_corrected_speed,
            "wind_capacity_factor": wind_capacity,
            "wind_power_density_w_m2": wind_power_density,
        }
    )
    hours = max(len(series), 1)
    peak_pv = series.loc[series["pv_power_kw_per_kwp"].idxmax(), "time"] if len(series) else None
    peak_wind = series.loc[series["wind_capacity_factor"].idxmax(), "time"] if len(series) else None
    return PhysicalEnergy(
        series=series,
        pv_yield_kwh_per_kwp=round(float(np.nansum(pv_kw_per_kwp)), 2),
        pv_capacity_factor_pct=round(float(np.nanmean(pv_kw_per_kwp) * 100.0), 1),
        wind_full_load_hours=round(float(np.nansum(wind_capacity)), 2),
        wind_capacity_factor_pct=round(float(np.nanmean(wind_capacity) * 100.0), 1),
        mean_wind_power_density_w_m2=round(float(np.nanmean(wind_power_density)), 1),
        peak_pv_time=peak_pv.isoformat() if peak_pv is not None else None,
        peak_wind_time=peak_wind.isoformat() if peak_wind is not None else None,
        notes=[
            f"PV yield models a south-facing {config.physical_energy.pv_tilt_degrees:g}-degree fixed array per installed kWp using plane-of-array irradiance and cell-temperature derating.",
            f"Wind output uses observed/modelled {config.physical_energy.wind_hub_height_m:g} m wind, moist-air density correction, and a generic {cut_in:g}/{rated:g}/{cut_out:g} m/s cut-in/rated/cut-out power curve.",
            "These are reference-system weather yields, not metered production or a forecast.",
        ],
    )
