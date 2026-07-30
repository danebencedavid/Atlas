from pathlib import Path

import pandas as pd

from atlas.anomalies import Anomaly
from atlas.config import AtlasConfig, OutputConfig
from atlas.electricity import ElectricitySummary
from atlas.energy import EnergyIndex
from atlas.profile import ModelProfile
from atlas.regimes import RegimeClassification
from atlas.site import archive_site
from atlas.site import build_site


def test_report_generation_smoke(tmp_path: Path):
    figure_paths = {}
    for name in [
        "meteogram",
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
    ]:
        path = tmp_path / f"{name}.html"
        path.write_text("placeholder", encoding="utf-8")
        figure_paths[name] = path

    processed = {}
    for name in ["period_metrics", "baseline_metrics", "anomalies", "electricity"]:
        path = tmp_path / f"{name}.csv"
        path.write_text("metric,value\nx,1\n", encoding="utf-8")
        processed[name] = path

    anomalies = [
        Anomaly("temperature_mean_c", "Temperature", 20, 18, 2, 1, 80, "deg C"),
        Anomaly("precipitation_total_mm", "Precipitation", 2, 5, -3, -1, 20, "mm"),
    ]
    config = AtlasConfig(outputs=OutputConfig(site_dir=tmp_path / "site"))

    target = build_site(
        config=config,
        period_start="2026-07-27",
        period_end="2026-07-29",
        current_metrics={},
        baseline_metrics={},
        anomalies=anomalies,
        energy=EnergyIndex(80, 45, 62.5, 10, 0, "solar-favored"),
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
        regime=RegimeClassification(
            "Sunny high-pressure period",
            "Clear and dry.",
            ["sunny"] * 3,
            ["dry"],
        ),
        figure_paths=figure_paths,
        processed_paths=processed,
    )

    assert target.exists()
    html = target.read_text(encoding="utf-8")
    assert "Atlas" in html
    assert "<iframe" in html
    assert "Hungary Electricity Context" in html
    assert "Advanced Meteorological Diagnostic" in html


def test_archive_site_copies_latest_dashboard_assets_and_data(tmp_path: Path):
    site_dir = tmp_path / "site"
    (site_dir / "assets").mkdir(parents=True)
    (site_dir / "data").mkdir()
    (site_dir / "index.html").write_text("<html>Atlas</html>", encoding="utf-8")
    (site_dir / "assets" / "meteogram.html").write_text("plot", encoding="utf-8")
    (site_dir / "data" / "summary.json").write_text("{}", encoding="utf-8")

    archived_index = archive_site(site_dir, tmp_path / "reports" / "weeks" / "2026-07-20_2026-07-26")

    assert archived_index.exists()
    assert (archived_index.parent / "assets" / "meteogram.html").exists()
    assert (archived_index.parent / "data" / "summary.json").exists()
