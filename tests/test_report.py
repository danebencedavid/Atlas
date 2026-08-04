from pathlib import Path
import json

import numpy as np
import pandas as pd

from atlas.analogs import AnalogAnalysis
from atlas.anomalies import Anomaly
from atlas.climatology import ClimateReference
from atlas.config import AtlasConfig, OutputConfig
from atlas.electricity import ElectricitySummary
from atlas.energy import EnergyIndex, PhysicalEnergy
from atlas.fronts import FrontAnalysis
from atlas.hungaromet import LightningArchive, RadarArchive, StationObservations
from atlas.land import LandSurfaceAnalysis
from atlas.phenomena import PhenomenaAnalysis
from atlas.profile import ModelProfile
from atlas.regimes import RegimeClassification
from atlas.satellite import SatelliteArchive
from atlas.site import archive_site
from atlas.site import build_site
from atlas.synoptic import SynopticArchive


def test_report_generation_smoke(tmp_path: Path):
    figure_paths = {}
    for name in [
        "meteogram",
        "daily_meteogram",
        "seven_day_context",
        "wind_rose",
        "pressure_tendency",
        "dewpoint_spread",
        "solar_diurnal",
        "anomaly_bars",
        "energy_quadrant",
        "regime_strip",
        "electricity_overview",
        "weather_electricity_links",
        "model_profile",
        "hodograph",
        "time_pressure",
        "station_comparison",
        "radar_archive",
        "lightning_diary",
        "synoptic_evolution",
        "physical_energy",
        "daily_physical_energy",
        "column_diagnostics",
        "satellite_diary",
        "climate_reference",
        "daily_climate_reference",
        "land_surface",
        "phenomena_timeline",
    ]:
        path = tmp_path / f"{name}.html"
        path.write_text("placeholder", encoding="utf-8")
        figure_paths[name] = path
    (tmp_path / "satellite_media").mkdir()
    (tmp_path / "satellite_media" / "frame.webp").write_bytes(b"fixture")

    processed = {}
    for name in [
        "current_hourly",
        "seven_day_context_hourly",
        "period_metrics",
        "baseline_metrics",
        "anomalies",
        "electricity",
        "model_profile",
        "model_profile_series",
        "model_profile_surface",
        "hungaromet_station",
        "radar_timeline",
        "radar_accumulation",
        "lightning",
        "frontal_passages",
        "historical_analogs",
        "synoptic_fields",
        "physical_energy",
    ]:
        path = tmp_path / f"{name}.csv"
        path.write_text("metric,value\nx,1\n", encoding="utf-8")
        processed[name] = path

    anomalies = [
        Anomaly("temperature_mean_c", "Temperature", 20, 18, 2, 1, 80, "deg C"),
        Anomaly("precipitation_total_mm", "Precipitation", 2, 5, -3, -1, 20, "mm"),
    ]
    config = AtlasConfig(outputs=OutputConfig(site_dir=tmp_path / "site"))
    climate = ClimateReference(
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        anomalies,
        anomalies,
        {item.metric: item.percentile for item in anomalies},
        ["Climate reference."],
    )
    empty_synoptic = SynopticArchive(
        times=[],
        latitudes=np.array([]),
        longitudes=np.array([]),
        pressure_msl_hpa=np.empty((0, 0, 0)),
        height_500m=np.empty((0, 0, 0)),
        height_300m=np.empty((0, 0, 0)),
        temperature_850c=np.empty((0, 0, 0)),
        wind_u_850ms=np.empty((0, 0, 0)),
        wind_v_850ms=np.empty((0, 0, 0)),
        wind_speed_300ms=np.empty((0, 0, 0)),
        vorticity_500_1e5_s=np.empty((0, 0, 0)),
        relative_humidity_700pct=np.empty((0, 0, 0)),
        vertical_velocity_700ms=np.empty((0, 0, 0)),
        theta_e_850k=np.empty((0, 0, 0)),
        temperature_advection_850c_3h=np.empty((0, 0, 0)),
        frontogenesis_850k_100km_3h=np.empty((0, 0, 0)),
        notes=["Synoptic archive unavailable."],
    )
    empty_physical = PhysicalEnergy(
        pd.DataFrame(), float("nan"), float("nan"), float("nan"), float("nan"),
        float("nan"), None, None, ["Physical energy unavailable."],
    )
    regime = RegimeClassification(
        "Sunny high-pressure period",
        "Sunny high-pressure period: temperature was +2.0 deg C versus normal, precipitation -3.0 mm, wind +0.0 m/s, and period solar radiation +500 Wh/m2.",
        ["sunny"] * 3,
        ["dry"],
    )

    target = build_site(
        config=config,
        period_start="2026-07-27",
        period_end="2026-07-29",
        daily_date="2026-07-29",
        current_metrics={},
        daily_metrics={},
        baseline_metrics={},
        anomalies=anomalies,
        climate_reference=climate,
        daily_climate_reference=climate,
        energy=EnergyIndex(80, 45, 62.5, 10, 0, "solar-favored"),
        daily_energy=EnergyIndex(80, 45, 62.5, 10, 0, "solar-favored"),
        electricity=ElectricitySummary(
            True,
            5000,
            6500,
            12000,
            1500,
            25,
            3800,
            80,
            140,
            600,
            "solar-led variable renewable output",
        ),
        electricity_notes=["Hungary-wide electricity context."],
        profile=ModelProfile(pd.DataFrame(), None, "Open-Meteo", {}, ["Model-derived profile."]),
        station=StationObservations(pd.DataFrame(), 64711, "Debrecen Airport", ["Station unavailable."]),
        radar=RadarArchive(
            [], np.array([]), np.array([]), np.empty((0, 0, 0)), np.empty((0, 0)),
            pd.DataFrame(), ["Radar unavailable."],
        ),
        lightning=LightningArchive(pd.DataFrame(), pd.DataFrame(), ["Lightning unavailable."]),
        satellite=SatelliteArchive({}, ["Satellite unavailable."]),
        fronts=FrontAnalysis([], pd.DataFrame(), ["No objective passage detected."]),
        phenomena=PhenomenaAnalysis([], ["No phenomena detected."]),
        analogs=AnalogAnalysis([], pd.DataFrame(), ["Analog archive unavailable."]),
        synoptic=empty_synoptic,
        land=LandSurfaceAnalysis(
            pd.DataFrame(), pd.DataFrame(), {}, {}, "Unavailable", ["Land unavailable."]
        ),
        physical_energy=empty_physical,
        daily_physical_energy=empty_physical,
        regime=regime,
        daily_regime=regime,
        figure_paths=figure_paths,
        processed_paths=processed,
        edition_notice="Demonstration edition: synthetic data.",
    )

    assert target.exists()
    html = target.read_text(encoding="utf-8")
    assert "Atlas" in html
    assert "<iframe" in html
    assert "Yesterday Hour By Hour" in html
    assert (target.parent / "weather.html").exists()
    assert not (target.parent / "assets" / "site").exists()
    assert (target.parent / "assets" / "satellite_media" / "frame.webp").exists()
    assert "Public report" in html
    assert "Meteorological analysis" in html
    assert 'class="app-shell"' in html
    assert 'class="source-key"' in html
    assert html.index("Yesterday Hour By Hour") < html.index("Deterministic interpretation.")
    assert "Demonstration edition: synthetic data." in html
    analysis_dir = target.parent / "analysis"
    analysis_html = (analysis_dir / "index.html").read_text(encoding="utf-8")
    assert "Demonstration edition: synthetic data." in analysis_html
    assert analysis_html.index("Annotated 72-Hour Meteogram") < analysis_html.index(
        "Deterministic interpretation."
    )
    assert "Wind Regime" in (analysis_dir / "surface-synoptic.html").read_text(encoding="utf-8")
    assert "Meteosat, Radar And Lightning" in (analysis_dir / "storms-satellite.html").read_text(encoding="utf-8")
    assert "Closest seasonal analogs" in (analysis_dir / "climate.html").read_text(encoding="utf-8")
    assert "Land Surface And Water Balance" in (analysis_dir / "land-energy.html").read_text(encoding="utf-8")
    upper_air = (analysis_dir / "upper-air.html").read_text(encoding="utf-8")
    assert "Hodograph" in upper_air
    assert "Time-Pressure Curtain" in upper_air
    assert "Parcel And Boundary-Layer" in upper_air
    assert "Climatological Reference Ledger" in (analysis_dir / "methods.html").read_text(encoding="utf-8")
    summary_text = (target.parent / "data" / "summary.json").read_text(encoding="utf-8")
    assert "NaN" not in summary_text
    assert json.loads(summary_text)["physical_energy"]["pv_yield_kwh_per_kwp"] is None


def test_archive_site_copies_latest_dashboard_assets_and_data(tmp_path: Path):
    site_dir = tmp_path / "site"
    (site_dir / "assets").mkdir(parents=True)
    (site_dir / "data").mkdir()
    (site_dir / "index.html").write_text("<html>Atlas</html>", encoding="utf-8")
    (site_dir / "weather.html").write_text("<html>Weather</html>", encoding="utf-8")
    (site_dir / "assets" / "meteogram.html").write_text("plot", encoding="utf-8")
    (site_dir / "data" / "summary.json").write_text("{}", encoding="utf-8")

    archived_index = archive_site(site_dir, tmp_path / "reports" / "weeks" / "2026-07-20_2026-07-26")

    assert archived_index.exists()
    assert (archived_index.parent / "assets" / "meteogram.html").exists()
    assert (archived_index.parent / "data" / "summary.json").exists()
    assert (archived_index.parent / "weather.html").exists()
