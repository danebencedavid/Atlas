from pathlib import Path

from atlas.anomalies import Anomaly
from atlas.config import AtlasConfig, OutputConfig
from atlas.energy import EnergyIndex
from atlas.regimes import RegimeClassification
from atlas.site import build_site


def test_report_generation_smoke(tmp_path: Path):
    figure_paths = {}
    for name in [
        "meteogram",
        "wind_rose",
        "pressure_tendency",
        "dewpoint_spread",
        "solar_diurnal",
        "anomaly_bars",
        "energy_quadrant",
        "regime_strip",
    ]:
        path = tmp_path / f"{name}.html"
        path.write_text("placeholder", encoding="utf-8")
        figure_paths[name] = path

    processed = {}
    for name in ["weekly_metrics", "baseline_metrics", "anomalies"]:
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
        week_start="2026-07-20",
        week_end="2026-07-26",
        current_metrics={},
        baseline_metrics={},
        anomalies=anomalies,
        energy=EnergyIndex(80, 45, 62.5, 10, 0, "solar-favored"),
        regime=RegimeClassification("Sunny high-pressure week", "Clear and dry.", ["sunny"] * 7, ["dry"]),
        figure_paths=figure_paths,
        processed_paths=processed,
    )

    assert target.exists()
    html = target.read_text(encoding="utf-8")
    assert "Atlas" in html
    assert "<iframe" in html
