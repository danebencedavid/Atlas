from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.almanac import build_almanac
from atlas.analogs import find_historical_analogs
from atlas.anomalies import anomalies_as_frame, period_metrics
from atlas.climatology import (
    build_climate_reference,
    fetch_climate_archive,
    standard_water_balance_samples,
)
from atlas.config import load_config
from atlas.dates import last_complete_period
from atlas.electricity import fetch_energy_charts, summarize_electricity
from atlas.energy import compute_energy_index, compute_physical_energy
from atlas.fronts import detect_fronts
from atlas.hungaromet import (
    fetch_lightning_archive,
    fetch_radar_archive,
    fetch_station_observations,
    station_hourly,
)
from atlas.kinematics import compute_storm_kinematics
from atlas.ingest import fetch_open_meteo_period
from atlas.land import analyze_land_surface
from atlas.phenomena import detect_weather_phenomena
from atlas.plots import generate_all_figures
from atlas.profile import fetch_model_profile
from atlas.radar_cells import analyse_radar_cells
from atlas.quality import DataQualityReport, validate_hourly_period
from atlas.regimes import classify_period
from atlas.satellite import fetch_satellite_archive
from atlas.serialization import json_ready
from atlas.site import build_site
from atlas.site import build_report_archive
from atlas.site import archive_site
from atlas.site import archive_public_site
from atlas.synoptic import fetch_synoptic_archive
from atlas.trajectory import compute_air_mass_origin, fetch_trajectory_field
from atlas.verification import verify_against_station


def parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def run_pipeline(
    config_path: str | Path = "configs/atlas.yml",
    period_start: date | None = None,
    today: date | None = None,
    refresh: bool = False,
    archive_analysis: bool = True,
) -> Path:
    config = load_config(config_path)
    quality_notes: list[str] = []
    if period_start is None:
        start, end = last_complete_period(
            today=today,
            tz_name=config.location.timezone,
            days=config.reporting.window_days,
        )
        current: pd.DataFrame | None = None
        quality: DataQualityReport | None = None
        for lag in range(config.operations.max_period_lag_days + 1):
            candidate_start = start - timedelta(days=lag)
            candidate_end = end - timedelta(days=lag)
            try:
                candidate = fetch_open_meteo_period(config, candidate_start, candidate_end, refresh=refresh)
                candidate_quality = validate_hourly_period(
                    candidate,
                    candidate_start,
                    candidate_end,
                    config.location.timezone,
                    minimum_coverage=config.operations.minimum_hourly_coverage,
                )
            except Exception as exc:
                quality_notes.append(f"{candidate_start.isoformat()} to {candidate_end.isoformat()} was unavailable: {exc}")
                continue
            if candidate_quality.ok:
                start, end = candidate_start, candidate_end
                current = candidate
                quality = candidate_quality
                if lag:
                    quality_notes.append(
                        f"Archive lag fallback used: selected {start.isoformat()} to {end.isoformat()} "
                        f"after the most recent rolling period was incomplete."
                    )
                quality_notes.extend(candidate_quality.notes)
                break
            quality_notes.extend(f"{candidate_start.isoformat()} to {candidate_end.isoformat()}: {note}" for note in candidate_quality.notes)
        if current is None or quality is None:
            raise RuntimeError(
                f"No complete weather archive found within {config.operations.max_period_lag_days} days. "
                f"Checks: {' | '.join(quality_notes)}"
            )
    else:
        start = period_start
        end = period_start + timedelta(days=config.reporting.window_days - 1)
        current = fetch_open_meteo_period(config, start, end, refresh=refresh)
        quality = validate_hourly_period(
            current,
            start,
            end,
            config.location.timezone,
            minimum_coverage=config.operations.minimum_hourly_coverage,
        )
        quality_notes.extend(quality.notes)
        if not quality.ok:
            raise RuntimeError(f"Requested period failed data-quality checks: {' '.join(quality.notes)}")

    data_dir = config.outputs.data_dir
    processed_dir = data_dir / "processed"
    period_slug = f"{start.isoformat()}_{end.isoformat()}"
    archive_dir = config.outputs.reports_dir / "periods" / period_slug
    figures_dir = config.outputs.reports_dir / "figures" / period_slug
    processed_dir.mkdir(parents=True, exist_ok=True)

    context_start = end - timedelta(days=config.reporting.context_days - 1)
    try:
        context = fetch_open_meteo_period(config, context_start, end, refresh=refresh)
        context_quality = validate_hourly_period(
            context,
            context_start,
            end,
            config.location.timezone,
            minimum_coverage=config.operations.minimum_hourly_coverage,
        )
        if not context_quality.ok:
            raise RuntimeError(" ".join(context_quality.notes))
    except Exception as exc:
        context = current.copy()
        quality_notes.append(f"Seven-day context was unavailable; the current period is shown instead: {exc}")

    climate_archive = fetch_climate_archive(config, start, refresh=refresh)
    almanac = build_almanac(climate_archive, config)
    station = fetch_station_observations(config, start, end, refresh=refresh)
    verification = verify_against_station(current, station)
    radar = fetch_radar_archive(config, start, end, refresh=refresh)
    radar_cells = analyse_radar_cells(radar, config)
    lightning = fetch_lightning_archive(config, start, end, refresh=refresh)
    satellite = fetch_satellite_archive(config, start, end, refresh=refresh)
    frontal_source = station_hourly(station) if not station.frame.empty else current
    fronts = detect_fronts(frontal_source)

    electricity_data = fetch_energy_charts(config, start, end, refresh=refresh)
    electricity_summary = summarize_electricity(electricity_data.frame)
    model_profile = fetch_model_profile(config, end, start_date=start, refresh=refresh)
    kinematics = compute_storm_kinematics(model_profile)
    trajectory_field = fetch_trajectory_field(config, start, end, refresh=refresh)
    air_mass_origin = compute_air_mass_origin(trajectory_field, config)
    analogs = find_historical_analogs(config, current, start, refresh=refresh)
    synoptic = fetch_synoptic_archive(config, start, end, refresh=refresh)

    land_start = end - timedelta(days=config.land_surface.context_days - 1)
    if not config.land_surface.enabled:
        land_frame = pd.DataFrame()
        quality_notes.append("Land-surface analysis is disabled in configuration.")
    else:
        try:
            land_frame = fetch_open_meteo_period(config, land_start, end, refresh=refresh)
        except Exception as exc:
            if config.land_surface.required:
                raise RuntimeError(f"Required land-surface context was unavailable: {exc}") from exc
            land_frame = pd.DataFrame()
            quality_notes.append(f"Land-surface context was unavailable: {exc}")

    current_metrics = period_metrics(current)
    climate_reference = build_climate_reference(
        config,
        climate_archive,
        current_metrics,
        start,
        end,
    )
    baseline_table = climate_reference.recent_table
    baseline_means = {
        column: float(pd.to_numeric(baseline_table[column], errors="coerce").mean())
        for column in baseline_table.columns
        if column != "baseline_year"
    }
    anomalies = climate_reference.standard_anomalies
    standard_means = {
        column: float(pd.to_numeric(climate_reference.standard_table[column], errors="coerce").mean())
        for column in climate_reference.standard_table.columns
        if column != "baseline_year"
    }
    energy = compute_energy_index(current_metrics, standard_means)
    physical_energy = compute_physical_energy(config, current)

    current_local_dates = pd.to_datetime(current["time"], utc=True).dt.tz_convert(
        config.location.timezone
    ).dt.date
    daily_frame = current[current_local_dates == end].copy()
    if daily_frame.empty:
        raise RuntimeError(f"The selected report contained no rows for public-report day {end}.")
    daily_metrics = period_metrics(daily_frame)
    daily_climate_reference = build_climate_reference(
        config,
        climate_archive,
        daily_metrics,
        end,
        end,
    )
    daily_standard_means = {
        column: float(pd.to_numeric(daily_climate_reference.standard_table[column], errors="coerce").mean())
        for column in daily_climate_reference.standard_table.columns
        if column != "baseline_year"
    }
    daily_energy = compute_energy_index(daily_metrics, daily_standard_means)
    daily_physical_energy = compute_physical_energy(config, daily_frame)

    balance_samples = {
        days: standard_water_balance_samples(config, climate_archive, end, days)
        for days in (7, 30, 90)
    }
    land = analyze_land_surface(
        land_frame,
        balance_samples,
        timezone_name=config.location.timezone,
    )

    current_with_local = current.copy()
    current_with_local["local_time"] = pd.to_datetime(current_with_local["time"], utc=True).dt.tz_convert(config.location.timezone)
    regime = classify_period(current_with_local, anomalies)
    daily_with_local = daily_frame.copy()
    daily_with_local["local_time"] = pd.to_datetime(
        daily_with_local["time"], utc=True
    ).dt.tz_convert(config.location.timezone)
    daily_regime = classify_period(daily_with_local, daily_climate_reference.standard_anomalies)
    phenomena = detect_weather_phenomena(
        current,
        station,
        radar,
        lightning,
        fronts,
        model_profile,
        config.location.timezone,
    )

    figure_paths = generate_all_figures(
        frame=current,
        context_frame=context,
        climate=climate_reference,
        daily_climate=daily_climate_reference,
        land=land,
        phenomena=phenomena,
        daily_frame=daily_frame,
        anomalies=anomalies,
        electricity=electricity_data.frame,
        electricity_summary=electricity_summary,
        profile=model_profile,
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
        air_mass_origin=air_mass_origin,
    )

    metrics_frame = pd.DataFrame(
        [
            {"metric": key, "value": value, "scope": "current"}
            for key, value in current_metrics.items()
        ]
        + [
            {"metric": key, "value": value, "scope": "baseline_mean"}
            for key, value in baseline_means.items()
        ]
    )
    period_metrics_path = processed_dir / "period_metrics.csv"
    baseline_metrics_path = processed_dir / "baseline_metrics.csv"
    standard_normal_metrics_path = processed_dir / "standard_normal_metrics.csv"
    full_record_metrics_path = processed_dir / "full_record_metrics.csv"
    anomalies_path = processed_dir / "anomalies.csv"
    recent_anomalies_path = processed_dir / "recent_anomalies.csv"
    current_hourly_path = processed_dir / "current_hourly.csv"
    context_hourly_path = processed_dir / "seven_day_context_hourly.csv"
    electricity_path = processed_dir / "electricity.csv"
    model_profile_path = processed_dir / "model_profile.csv"
    model_profile_series_path = processed_dir / "model_profile_series.csv"
    model_profile_surface_path = processed_dir / "model_profile_surface_series.csv"
    station_path = processed_dir / "hungaromet_station_observations.csv"
    radar_timeline_path = processed_dir / "radar_timeline.csv"
    radar_grid_path = processed_dir / "radar_accumulation.npz"
    lightning_path = processed_dir / "lightning_events.csv"
    fronts_path = processed_dir / "frontal_passages.csv"
    analogs_path = processed_dir / "historical_analogs.csv"
    synoptic_path = processed_dir / "synoptic_fields.npz"
    physical_energy_path = processed_dir / "physical_energy.csv"
    daily_physical_energy_path = processed_dir / "daily_physical_energy.csv"
    satellite_manifest_path = processed_dir / "satellite_manifest.csv"
    phenomena_path = processed_dir / "weather_phenomena.csv"
    land_hourly_path = processed_dir / "land_surface_hourly.csv"
    land_daily_path = processed_dir / "land_surface_daily.csv"
    summary_path = processed_dir / "summary.json"

    metrics_frame.to_csv(period_metrics_path, index=False)
    baseline_table.to_csv(baseline_metrics_path, index=False)
    climate_reference.standard_table.to_csv(standard_normal_metrics_path, index=False)
    climate_reference.full_record_table.to_csv(full_record_metrics_path, index=False)
    anomalies_as_frame(anomalies).to_csv(anomalies_path, index=False)
    anomalies_as_frame(climate_reference.recent_anomalies).to_csv(recent_anomalies_path, index=False)
    current.to_csv(current_hourly_path, index=False)
    context.to_csv(context_hourly_path, index=False)
    electricity_data.frame.to_csv(electricity_path, index=False)
    model_profile.frame.to_csv(model_profile_path, index=False)
    model_profile.series.to_csv(model_profile_series_path, index=False)
    model_profile.surface_series.to_csv(model_profile_surface_path, index=False)
    station.frame.to_csv(station_path, index=False)
    radar.timeline.to_csv(radar_timeline_path, index=False)
    np.savez_compressed(
        radar_grid_path,
        latitudes=radar.latitudes,
        longitudes=radar.longitudes,
        accumulation_mm=radar.accumulation_mm,
    )
    lightning.frame.to_csv(lightning_path, index=False)
    pd.DataFrame(
        [
            {
                **asdict(event),
                "time": event.time.isoformat(),
            }
            for event in fronts.events
        ]
    ).to_csv(fronts_path, index=False)
    pd.DataFrame([asdict(match) for match in analogs.matches]).to_csv(analogs_path, index=False)
    np.savez_compressed(
        synoptic_path,
        times=np.array([timestamp.isoformat() for timestamp in synoptic.times]),
        latitudes=synoptic.latitudes,
        longitudes=synoptic.longitudes,
        pressure_msl_hpa=synoptic.pressure_msl_hpa,
        height_500m=synoptic.height_500m,
        height_300m=synoptic.height_300m,
        temperature_850c=synoptic.temperature_850c,
        wind_u_850ms=synoptic.wind_u_850ms,
        wind_v_850ms=synoptic.wind_v_850ms,
        wind_speed_300ms=synoptic.wind_speed_300ms,
        vorticity_500_1e5_s=synoptic.vorticity_500_1e5_s,
        relative_humidity_700pct=synoptic.relative_humidity_700pct,
        vertical_velocity_700ms=synoptic.vertical_velocity_700ms,
        theta_e_850k=synoptic.theta_e_850k,
        temperature_advection_850c_3h=synoptic.temperature_advection_850c_3h,
        frontogenesis_850k_100km_3h=synoptic.frontogenesis_850k_100km_3h,
    )
    physical_energy.series.to_csv(physical_energy_path, index=False)
    daily_physical_energy.series.to_csv(daily_physical_energy_path, index=False)
    pd.DataFrame(
        [
            {"time": frame.time.isoformat(), "product": frame.product, "source_file": frame.path.name}
            for frames in satellite.frames.values()
            for frame in frames
        ]
    ).to_csv(satellite_manifest_path, index=False)
    pd.DataFrame([asdict(event) for event in phenomena.events]).to_csv(phenomena_path, index=False)
    land.hourly.to_csv(land_hourly_path, index=False)
    land.daily.to_csv(land_daily_path, index=False)
    summary_path.write_text(
        json.dumps(
            json_ready({
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "daily_date": end.isoformat(),
                "context_start": context_start.isoformat(),
                "context_end": end.isoformat(),
                "energy": asdict(energy),
                "daily_energy": asdict(daily_energy),
                "electricity": asdict(electricity_summary),
                "electricity_notes": electricity_data.notes,
                "model_profile": {
                    "valid_time": (
                        model_profile.valid_time.isoformat()
                        if model_profile.valid_time is not None
                        else None
                    ),
                    "source": model_profile.source,
                    "diagnostics": model_profile.diagnostics,
                    "notes": model_profile.notes,
                },
                "hungaromet_station": {
                    "station_id": station.station_id,
                    "station_name": station.station_name,
                    "records": len(station.frame),
                    "notes": station.notes,
                },
                "radar": {
                    "frames": len(radar.times),
                    "maximum_reflectivity_dbz": (
                        float(radar.timeline["domain_max_dbz"].max())
                        if not radar.timeline.empty
                        else None
                    ),
                    "notes": radar.notes,
                },
                "lightning": {
                    "events": len(lightning.frame),
                    "closest_event_km": (
                        float(lightning.frame["distance_km"].min())
                        if not lightning.frame.empty
                        else None
                    ),
                    "notes": lightning.notes,
                },
                "satellite": {
                    "frames": satellite.frame_count,
                    "products": {name: len(frames) for name, frames in satellite.frames.items()},
                    "notes": satellite.notes,
                },
                "frontal_passages": [
                    {**asdict(event), "time": event.time.isoformat()} for event in fronts.events
                ],
                "front_notes": fronts.notes,
                "weather_phenomena": [asdict(event) for event in phenomena.events],
                "phenomena_notes": phenomena.notes,
                "historical_analogs": [asdict(match) for match in analogs.matches],
                "analog_notes": analogs.notes,
                "synoptic": {"frames": len(synoptic.times), "notes": synoptic.notes},
                "climatology": {
                    "standard_period": (
                        f"{config.climatology.standard_start_year}-"
                        f"{config.climatology.standard_end_year}"
                    ),
                    "standard_anomalies": [asdict(item) for item in climate_reference.standard_anomalies],
                    "recent_anomalies": [asdict(item) for item in climate_reference.recent_anomalies],
                    "full_record_percentiles": climate_reference.full_record_percentiles,
                    "notes": climate_reference.notes,
                },
                "land_surface": {
                    "metrics": land.metrics,
                    "water_balance_percentiles": land.water_balance_percentiles,
                    "moisture_context": land.moisture_context,
                    "notes": land.notes,
                },
                "physical_energy": {
                    "pv_yield_kwh_per_kwp": physical_energy.pv_yield_kwh_per_kwp,
                    "pv_capacity_factor_pct": physical_energy.pv_capacity_factor_pct,
                    "wind_full_load_hours": physical_energy.wind_full_load_hours,
                    "wind_capacity_factor_pct": physical_energy.wind_capacity_factor_pct,
                    "mean_wind_power_density_w_m2": physical_energy.mean_wind_power_density_w_m2,
                    "peak_pv_time": physical_energy.peak_pv_time,
                    "peak_wind_time": physical_energy.peak_wind_time,
                    "notes": physical_energy.notes,
                },
                "regime": asdict(regime),
                "daily_regime": asdict(daily_regime),
                "current_metrics": current_metrics,
                "daily_metrics": daily_metrics,
                "baseline_metrics": baseline_means,
                "data_quality": asdict(quality),
                "quality_notes": quality_notes,
            }),
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    site_index = build_site(
        config=config,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        daily_date=end.isoformat(),
        current_metrics=current_metrics,
        daily_metrics=daily_metrics,
        baseline_metrics=baseline_means,
        anomalies=anomalies,
        climate_reference=climate_reference,
        daily_climate_reference=daily_climate_reference,
        energy=energy,
        daily_energy=daily_energy,
        electricity=electricity_summary,
        electricity_notes=electricity_data.notes,
        profile=model_profile,
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
        almanac=almanac,
        verification=verification,
        kinematics=kinematics,
        air_mass_origin=air_mass_origin,
        radar_cells=radar_cells,
        figure_paths=figure_paths,
        processed_paths={
            "period_metrics": period_metrics_path,
            "baseline_metrics": baseline_metrics_path,
            "standard_normal_metrics": standard_normal_metrics_path,
            "full_record_metrics": full_record_metrics_path,
            "anomalies": anomalies_path,
            "recent_anomalies": recent_anomalies_path,
            "current_hourly": current_hourly_path,
            "seven_day_context_hourly": context_hourly_path,
            "electricity": electricity_path,
            "model_profile": model_profile_path,
            "model_profile_series": model_profile_series_path,
            "model_profile_surface": model_profile_surface_path,
            "hungaromet_station": station_path,
            "radar_timeline": radar_timeline_path,
            "radar_accumulation": radar_grid_path,
            "lightning": lightning_path,
            "satellite_manifest": satellite_manifest_path,
            "frontal_passages": fronts_path,
            "phenomena": phenomena_path,
            "historical_analogs": analogs_path,
            "synoptic_fields": synoptic_path,
            "physical_energy": physical_energy_path,
            "daily_physical_energy": daily_physical_energy_path,
            "land_surface_hourly": land_hourly_path,
            "land_surface_daily": land_daily_path,
            "summary": summary_path,
        },
        quality_notes=quality_notes,
    )
    daily_archive_dir = config.outputs.reports_dir / "daily" / end.isoformat()
    archive_public_site(
        site_index.parent,
        daily_archive_dir,
        {
            figure_paths["daily_meteogram"].name,
            figure_paths["daily_physical_energy"].name,
            figure_paths["seven_day_context"].name,
            figure_paths["daily_climate_reference"].name,
        },
    )
    if archive_analysis:
        archive_site(site_index.parent, archive_dir)
    build_report_archive(config, site_index.parent, config.outputs.reports_dir)
    return site_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Atlas rolling three-day static weather dashboard.")
    parser.add_argument("--config", default="configs/atlas.yml", help="Path to Atlas YAML config.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Build a clearly labelled deterministic demo site without calling external APIs.",
    )
    parser.add_argument(
        "--period-start",
        "--week-start",
        dest="period_start",
        help="Explicit reporting-period start date, YYYY-MM-DD.",
    )
    parser.add_argument("--today", help="Override today's date for last-complete-period calculation, YYYY-MM-DD.")
    parser.add_argument("--refresh", action="store_true", help="Refetch API data instead of using cached raw responses.")
    parser.add_argument(
        "--skip-analysis-archive",
        action="store_true",
        help="Build the live 72-hour analysis without committing a heavy analysis archive.",
    )
    args = parser.parse_args()

    if args.demo:
        from atlas.demo import run_demo_pipeline

        output = run_demo_pipeline(
            config_path=args.config,
            today=parse_date(args.today),
        )
        print(f"Built Atlas demonstration site: {output}")
        return

    output = run_pipeline(
        config_path=args.config,
        period_start=parse_date(args.period_start),
        today=parse_date(args.today),
        refresh=args.refresh,
        archive_analysis=not args.skip_analysis_archive,
    )
    print(f"Built Atlas site: {output}")


if __name__ == "__main__":
    main()
