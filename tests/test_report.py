from pathlib import Path
import json

import numpy as np
import pandas as pd

from atlas.almanac import build_almanac
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
from atlas.site import archive_public_site
from atlas.site import archive_site
from atlas.site import build_report_archive
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
    almanac_dates = pd.date_range("2020-01-01", "2022-12-31", freq="D")
    almanac = build_almanac(
        pd.DataFrame(
            {
                "date": almanac_dates.date,
                "temperature_2m_mean": 10.0,
                "precipitation_sum": 1.0,
                "wind_speed_100m_mean": 4.0,
                "pressure_msl_mean": 1013.0,
                "cloud_cover_mean": 50.0,
                "shortwave_radiation_sum": 5.0,
                "et0_fao_evapotranspiration_sum": 1.0,
            }
        ),
        config,
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
        almanac=almanac,
        figure_paths=figure_paths,
        processed_paths=processed,
        edition_notice="Demonstration edition: synthetic data.",
    )

    assert target.exists()
    html = target.read_text(encoding="utf-8")
    assert "Atlas" in html
    assert "What kind of weather did Debrecen just have" in html
    assert "Current publications" in html
    assert 'href="report.html"' in html
    assert 'href="analysis/index.html"' in html
    assert 'href="archive/index.html"' in html
    assert "Scientific frame" in html
    assert "<iframe" not in html
    report_html = (target.parent / "report.html").read_text(encoding="utf-8")
    assert "<iframe" in report_html
    assert "Yesterday Hour By Hour" in report_html
    assert (target.parent / "weather.html").exists()
    assert not (target.parent / "assets" / "site").exists()
    assert (target.parent / "assets" / "satellite_media" / "frame.webp").exists()
    assert "Public report" in html
    assert "Meteorological analysis" in html
    assert 'class="app-shell"' in html
    assert 'class="source-key"' in report_html
    assert 'href="archive/index.html"' in html
    assert 'class="archive-nav-link"' in html
    assert ">History<" in html
    assert report_html.index("Yesterday Hour By Hour") < report_html.index("Deterministic interpretation.")
    assert "Demonstration edition: synthetic data." in html
    analysis_dir = target.parent / "analysis"
    analysis_html = (analysis_dir / "index.html").read_text(encoding="utf-8")
    assert "Demonstration edition: synthetic data." in analysis_html
    assert 'href="../archive/index.html"' in analysis_html
    assert 'href="story.html"' in analysis_html
    assert analysis_html.index("Annotated 72-Hour Meteogram") < analysis_html.index(
        "Deterministic interpretation."
    )
    story_html = (analysis_dir / "story.html").read_text(encoding="utf-8")
    assert "Weather Story Graph" in story_html
    assert 'id="weather-story-data"' in story_html
    assert "Connections" in story_html
    assert "Solar-Wind Weather Quadrant" not in (
        analysis_dir / "land-energy.html"
    ).read_text(encoding="utf-8")
    assert (target.parent / "data" / "weather_story.json").exists()
    assert "Wind Regime" in (analysis_dir / "surface-synoptic.html").read_text(encoding="utf-8")
    assert "Meteosat, Radar And Lightning" in (analysis_dir / "storms-satellite.html").read_text(encoding="utf-8")
    assert "Closest seasonal analogs" in (analysis_dir / "climate.html").read_text(encoding="utf-8")
    assert "Land Surface And Water Balance" in (analysis_dir / "land-energy.html").read_text(encoding="utf-8")
    upper_air = (analysis_dir / "upper-air.html").read_text(encoding="utf-8")
    assert "Hodograph" in upper_air
    assert "Time-Pressure Curtain" in upper_air
    assert "Parcel And Boundary-Layer" in upper_air
    methods_html = (analysis_dir / "methods.html").read_text(encoding="utf-8")
    assert "Climatological Reference Ledger" in methods_html
    assert "Data Downloads" in methods_html
    assert 'class="download-list"' in methods_html
    assert 'class="download-filemark"' in methods_html
    assert 'class="download-action">Download' in methods_html
    summary_text = (target.parent / "data" / "summary.json").read_text(encoding="utf-8")
    assert "NaN" not in summary_text
    assert json.loads(summary_text)["physical_energy"]["pv_yield_kwh_per_kwp"] is None

    assert (target.parent / "data" / "climate_almanac.json").exists()
    assert 'href="summary.html"' in html
    assert 'href="records.html"' in html
    summary_page = (target.parent / "summary.html").read_text(encoding="utf-8")
    assert "Season &amp; Month Summary" in summary_page
    # Months and seasons share one select, so there is no mode toggle to fall out of sync.
    assert "data-summary-mode-button" not in summary_page
    assert summary_page.count("<select data-summary-select") == 1
    assert '<optgroup label="Months">' in summary_page
    assert '<optgroup label="Seasons">' in summary_page
    assert 'value="month:1">January</option>' in summary_page
    assert 'value="season:Winter">Winter</option>' in summary_page
    assert "data-summary-panel" in summary_page
    records_page = (target.parent / "records.html").read_text(encoding="utf-8")
    assert "All-Time Record Book" in records_page
    assert 'class="record-grid"' in records_page
    # The share control belongs only to the report and the analysis, never to the
    # landing, summary, record or archive pages, which cover no single period.
    for pageless in (html, summary_page, records_page):
        assert "data-atlas-share-button" not in pageless
        assert 'id="atlas-share-data"' not in pageless

    site_root = target.parent
    analysis_page = (site_root / "analysis" / "index.html").read_text(encoding="utf-8")
    for shareable in (report_html, analysis_page):
        assert "data-atlas-share-button" in shareable
        assert 'id="atlas-share-data"' in shareable
        # The menu replaces the old single button that opened the OS share sheet.
        assert 'data-atlas-share-action="download"' in shareable
        assert 'data-atlas-share-action="facebook"' in shareable
        assert 'data-atlas-share-action="x"' in shareable
        assert 'data-atlas-share-action="whatsapp"' in shareable
        assert "Share this report" in shareable
        assert "Share today's weather" not in shareable
        # Link shares carry a URL, so the preview only renders with Open Graph tags.
        assert '<meta property="og:image"' in shareable
        assert '<meta name="twitter:card" content="summary_large_image">' in shareable

    assert '<link rel="canonical" href="https://danebencedavid.github.io/Atlas/report.html">' in report_html
    assert (
        '<link rel="canonical" href="https://danebencedavid.github.io/Atlas/analysis/index.html">'
        in analysis_page
    )

    # The daily report and the 72-hour analysis describe different periods, so each
    # carries its own card rather than one standing in for the other.
    daily_card = site_root / "assets" / "share-card.png"
    analysis_card = site_root / "assets" / "share-card-analysis.png"
    assert daily_card.is_file()
    assert analysis_card.is_file()
    assert daily_card.read_bytes() != analysis_card.read_bytes()

    assert "assets/share-card-analysis.png" in analysis_page
    assert "assets/share-card-analysis.png" not in report_html
    assert "assets/share-card.png" in report_html
    assert '"kind_label": "72-hour analysis"' in analysis_page
    assert '"kind_label": "Daily report"' in report_html


def test_archive_public_site_uses_daily_report_as_archive_index(tmp_path: Path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text("project home", encoding="utf-8")
    (site_dir / "report.html").write_text("daily overview", encoding="utf-8")
    (site_dir / "weather.html").write_text("daily weather", encoding="utf-8")
    (site_dir / "assets").mkdir()
    (site_dir / "assets" / "daily.html").write_text("plot", encoding="utf-8")

    archived_index = archive_public_site(
        site_dir,
        tmp_path / "reports" / "daily" / "2026-08-03",
        {"daily.html"},
    )

    assert archived_index.read_text(encoding="utf-8") == "daily overview"
    assert (archived_index.parent / "weather.html").exists()
    assert (archived_index.parent / "assets" / "daily.html").exists()
    assert not (archived_index.parent / "report.html").exists()


def test_archive_site_copies_latest_dashboard_assets_and_data(tmp_path: Path):
    site_dir = tmp_path / "site"
    (site_dir / "assets").mkdir(parents=True)
    (site_dir / "data").mkdir()
    (site_dir / "index.html").write_text("<html>Atlas</html>", encoding="utf-8")
    (site_dir / "weather.html").write_text("<html>Weather</html>", encoding="utf-8")
    (site_dir / "assets" / "meteogram.html").write_text("plot", encoding="utf-8")
    (site_dir / "data" / "summary.json").write_text("{}", encoding="utf-8")
    (site_dir / "archive").mkdir()
    (site_dir / "archive" / "index.html").write_text("old archive", encoding="utf-8")

    archived_index = archive_site(site_dir, tmp_path / "reports" / "weeks" / "2026-07-20_2026-07-26")

    assert archived_index.exists()
    assert (archived_index.parent / "assets" / "meteogram.html").exists()
    assert (archived_index.parent / "data" / "summary.json").exists()
    assert (archived_index.parent / "weather.html").exists()
    assert not (archived_index.parent / "archive").exists()


def test_build_report_archive_publishes_saved_editions(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    daily = reports_dir / "daily" / "2026-08-03"
    period = reports_dir / "periods" / "2026-08-01_2026-08-03"
    weekly = reports_dir / "weeks" / "2026-07-20_2026-07-26"
    (daily / "assets").mkdir(parents=True)
    (period / "analysis").mkdir(parents=True)
    weekly.mkdir(parents=True)

    (daily / "index.html").write_text(
        '<!doctype html><html><head><style>body{color:red}</style></head><body>'
        '<header class="site-header"><a href="analysis/index.html">Analysis</a>'
        '<a href="archive/index.html">Archive</a></header>'
        '<main><div class="page-shell"><h1>Saved daily report</h1></div></main>'
        '<footer>Daily footer</footer></body></html>',
        encoding="utf-8",
    )
    (daily / "weather.html").write_text(
        '<!doctype html><html><head></head><body><header class="site-header">Old navigation</header>'
        '<main><div class="page-shell">Daily weather</div></main></body></html>',
        encoding="utf-8",
    )
    (daily / "assets" / "daily.html").write_text("plot", encoding="utf-8")
    (period / "index.html").write_text(
        '<!doctype html><html><head></head><body><header class="site-header">Old navigation</header>'
        '<main><div class="page-shell">Period public report</div></main></body></html>',
        encoding="utf-8",
    )
    (period / "analysis" / "index.html").write_text(
        '<!doctype html><html><head></head><body><header class="site-header">Old navigation</header>'
        '<main><div class="page-shell">Period analysis</div></main></body></html>',
        encoding="utf-8",
    )
    (weekly / "index.html").write_text(
        '<!doctype html><html><head></head><body><header><div class="wrap hero"><h1>Atlas</h1>'
        '</div></header><main><div class="wrap"><section>Weekly data</section></div></main>'
        '<footer><div class="wrap">Weekly footer</div></footer></body></html>',
        encoding="utf-8",
    )

    config = AtlasConfig(
        outputs=OutputConfig(
            site_dir=tmp_path / "site",
            reports_dir=reports_dir,
        )
    )
    index = build_report_archive(config, updated="2026-08-04 12:00 UTC")

    archive_html = index.read_text(encoding="utf-8")
    assert "Report Archive" in archive_html
    assert '<span>All editions</span><strong>3</strong>' in archive_html
    assert 'class="archive-nav-link"' in archive_html
    assert 'aria-current="page"' in archive_html
    assert "daily/2026-08-03/index.html" in archive_html
    assert "periods/2026-08-01_2026-08-03/analysis/index.html" in archive_html
    assert "weeks/2026-07-20_2026-07-26/index.html" in archive_html
    assert (index.parent / "daily" / "2026-08-03" / "assets" / "daily.html").exists()

    published_daily = (
        index.parent / "daily" / "2026-08-03" / "index.html"
    ).read_text(encoding="utf-8")
    assert 'href="../../index.html#analysis-reports"' in published_daily
    assert 'href="../../index.html"' in published_daily
    assert 'class="app-shell"' in published_daily
    assert 'data-atlas-restyled="true"' in published_daily
    assert "Saved daily report" in published_daily
    published_analysis = (
        index.parent / "periods" / "2026-08-01_2026-08-03" / "analysis" / "index.html"
    ).read_text(encoding="utf-8")
    assert 'href="../../../index.html"' in published_analysis
    assert 'class="app-shell"' in published_analysis
    assert "Period analysis" in published_analysis
    published_weekly = (
        index.parent / "weeks" / "2026-07-20_2026-07-26" / "index.html"
    ).read_text(encoding="utf-8")
    assert 'class="app-shell"' in published_weekly
    assert 'class="archived-legacy-content"' in published_weekly
    assert "Weekly data" in published_weekly
