from __future__ import annotations

import html
import json
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from atlas.analogs import AnalogAnalysis
from atlas.anomalies import Anomaly
from atlas.config import AtlasConfig
from atlas.electricity import ElectricitySummary
from atlas.energy import EnergyIndex, PhysicalEnergy
from atlas.fronts import FrontAnalysis
from atlas.hungaromet import LightningArchive, RadarArchive, StationObservations
from atlas.profile import ModelProfile
from atlas.regimes import RegimeClassification
from atlas.serialization import json_ready
from atlas.synoptic import SynopticArchive


PAGES = (
    ("index.html", "Overview"),
    ("weather.html", "Weather"),
    ("storms.html", "Storms"),
    ("upper-air.html", "Upper Air"),
    ("climate.html", "Climate"),
    ("energy.html", "Energy"),
    ("methods.html", "Methods"),
)

SHARED_CSS = """
:root {
  --ink: #172033;
  --muted: #667085;
  --line: #d9e0ea;
  --paper: #f7f9fc;
  --panel: #ffffff;
  --blue: #2563eb;
  --blue-soft: #eff6ff;
  --green: #047857;
  --gold: #a16207;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink);
  background: var(--panel);
  line-height: 1.5;
  overflow-x: hidden;
}
a { color: var(--blue); }
.site-header {
  position: sticky;
  top: 0;
  z-index: 30;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(10px);
}
.nav-wrap {
  width: min(100%, 1480px);
  min-height: 60px;
  margin: 0 auto;
  padding: 0 28px;
  display: flex;
  align-items: center;
  gap: 30px;
}
.brand {
  flex: 0 0 auto;
  color: var(--ink);
  font-weight: 800;
  text-decoration: none;
  font-size: 1.05rem;
}
.primary-nav {
  display: flex;
  align-items: stretch;
  gap: 4px;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
}
.primary-nav::-webkit-scrollbar { display: none; }
.primary-nav a {
  display: flex;
  align-items: center;
  min-height: 60px;
  padding: 0 13px;
  color: #475467;
  border-bottom: 3px solid transparent;
  font-size: 0.92rem;
  font-weight: 650;
  text-decoration: none;
  white-space: nowrap;
}
.primary-nav a:hover { color: var(--ink); }
.primary-nav a[aria-current="page"] {
  color: var(--blue);
  border-bottom-color: var(--blue);
}
.page-shell {
  width: min(100%, 1480px);
  margin: 0 auto;
  padding: 34px 28px 54px;
}
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.9fr);
  gap: 40px;
  align-items: end;
  min-height: 290px;
  padding: 20px 0 42px;
}
.eyebrow {
  margin-bottom: 8px;
  color: var(--blue);
  font-size: 0.78rem;
  font-weight: 800;
  text-transform: uppercase;
}
h1, h2, h3, p { letter-spacing: 0; }
h1 {
  margin: 0 0 12px;
  font-size: clamp(3.4rem, 7vw, 6.4rem);
  line-height: 0.94;
}
h2 {
  margin: 0;
  font-size: 1.36rem;
  line-height: 1.25;
}
.hero-regime {
  margin: 0 0 10px;
  font-size: 1.35rem;
  font-weight: 760;
}
.brief {
  max-width: 780px;
  margin: 0 0 12px;
  color: #344054;
  font-size: 1.12rem;
}
.meta, .source-note, footer {
  color: var(--muted);
  font-size: 0.92rem;
}
.page-intro {
  max-width: 930px;
  padding: 20px 0 34px;
}
.page-intro h1 {
  margin-bottom: 10px;
  font-size: clamp(2.3rem, 5vw, 4.2rem);
}
.page-intro p {
  margin: 0;
  color: #475467;
  font-size: 1.05rem;
}
.summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.score {
  min-width: 0;
  padding: 16px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.score strong {
  display: block;
  margin: 2px 0;
  font-size: 2rem;
  line-height: 1.1;
}
.score span {
  display: block;
  color: var(--muted);
  font-size: 0.88rem;
  overflow-wrap: anywhere;
}
.plot-section, .content-section {
  min-width: 0;
  padding: 30px 0 38px;
  border-top: 1px solid var(--line);
}
.section-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 15px;
}
.plot-help {
  position: relative;
  z-index: 5;
}
.plot-help summary {
  display: grid;
  width: 25px;
  height: 25px;
  place-items: center;
  color: var(--blue);
  background: var(--blue-soft);
  border: 1px solid #bfdbfe;
  border-radius: 50%;
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 800;
  list-style: none;
  user-select: none;
}
.plot-help summary::-webkit-details-marker { display: none; }
.plot-help summary:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.28);
  outline-offset: 2px;
}
.help-panel {
  position: absolute;
  top: 34px;
  left: -8px;
  z-index: 10;
  width: min(380px, calc(100vw - 56px));
  padding: 13px 15px;
  color: #344054;
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 6px;
  box-shadow: 0 12px 32px rgba(16, 24, 40, 0.15);
  font-size: 0.9rem;
  font-weight: 450;
}
.viz-frame {
  display: block;
  width: 100%;
  height: 640px;
  min-width: 0;
  border: 1px solid #e6eaf0;
  border-radius: 6px;
  background: #ffffff;
}
.viz-scroll {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
  border-radius: 6px;
}
.viz-frame.meteogram { height: 1000px; }
.viz-frame.context { height: 740px; }
.viz-frame.electricity { height: 840px; }
.viz-frame.relationships { height: 800px; }
.viz-frame.profile, .viz-frame.time-pressure { height: 840px; }
.viz-frame.hodograph { height: 780px; }
.viz-frame.radar, .viz-frame.synoptic, .viz-frame.physical-energy { height: 780px; }
.viz-frame.compact { height: 280px; }
.metric-band {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0 0 18px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.metric {
  min-width: 0;
  padding: 17px 18px;
  border-right: 1px solid var(--line);
}
.metric:last-child { border-right: 0; }
.metric span {
  display: block;
  color: var(--muted);
  font-size: 0.85rem;
}
.metric strong {
  display: block;
  margin: 3px 0;
  font-size: 1.55rem;
}
.analysis-lead {
  max-width: 1020px;
  margin: 0 0 18px;
  padding: 18px 0 18px 22px;
  border-left: 4px solid var(--blue);
  color: #344054;
  font-size: 1.08rem;
}
.analysis-lead strong { color: var(--ink); }
.insight-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.insight {
  min-width: 0;
  padding: 20px 22px;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.insight:nth-child(2n) { border-right: 0; }
.insight:nth-last-child(-n+2) { border-bottom: 0; }
.insight .provenance, .provenance {
  display: inline-block;
  margin-bottom: 7px;
  color: var(--blue);
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
}
.insight h3 { margin: 0 0 5px; font-size: 1.04rem; }
.insight p { margin: 0; color: #475467; }
.event-list { margin: 0; padding: 0; list-style: none; border-top: 1px solid var(--line); }
.event-list li {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 22px;
  padding: 18px 0;
  border-bottom: 1px solid var(--line);
}
.event-time { color: var(--muted); font-size: 0.9rem; font-weight: 700; }
.event-copy strong { display: block; margin-bottom: 4px; }
.event-copy p { margin: 0; color: #475467; }
.diagnostic-ledger {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.diagnostic-ledger div { padding: 16px; border-right: 1px solid var(--line); }
.diagnostic-ledger div:last-child { border-right: 0; }
.diagnostic-ledger span { display: block; color: var(--muted); font-size: 0.8rem; }
.diagnostic-ledger strong { display: block; margin-top: 3px; font-size: 1.25rem; }
.analog-list { border-top: 1px solid var(--line); }
.analog-row {
  display: grid;
  grid-template-columns: 170px 100px minmax(0, 1fr);
  gap: 20px;
  align-items: baseline;
  padding: 16px 0;
  border-bottom: 1px solid var(--line);
}
.analog-row strong { font-size: 1.08rem; }
.analog-row span { color: var(--muted); }
.table-scroll { overflow-x: auto; }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.94rem;
}
th, td {
  padding: 11px 9px;
  border-bottom: 1px solid var(--line);
  text-align: right;
  white-space: nowrap;
}
th:first-child, td:first-child { text-align: left; }
.methods-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 44px;
}
.methods-grid section { min-width: 0; }
ul { margin: 8px 0 0; padding-left: 20px; }
.download-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 28px;
  padding: 0;
  list-style: none;
}
.download-list a {
  display: block;
  padding: 9px 0;
  border-bottom: 1px solid var(--line);
  text-decoration: none;
}
footer {
  border-top: 1px solid var(--line);
  background: var(--paper);
}
.footer-wrap {
  width: min(100%, 1480px);
  margin: 0 auto;
  padding: 22px 28px;
}
@media (max-width: 860px) {
  .nav-wrap { padding: 0 18px; gap: 16px; }
  .hero { grid-template-columns: 1fr; min-height: 0; padding-top: 10px; }
  .page-shell { padding: 24px 18px 40px; }
  .summary, .metric-band, .methods-grid, .download-list, .insight-grid,
  .diagnostic-ledger { grid-template-columns: 1fr; }
  .insight, .insight:nth-child(2n), .insight:nth-last-child(-n+2),
  .diagnostic-ledger div { border-right: 0; border-bottom: 1px solid var(--line); }
  .insight:last-child, .diagnostic-ledger div:last-child { border-bottom: 0; }
  .event-list li, .analog-row { grid-template-columns: 1fr; gap: 4px; }
  .metric { border-right: 0; border-bottom: 1px solid var(--line); }
  .metric:last-child { border-bottom: 0; }
  h1 { font-size: 3.5rem; }
  .viz-frame { height: 570px; }
  .viz-frame { min-width: 720px; }
  .viz-frame.compact { min-width: 520px; }
  .viz-frame.meteogram { height: 940px; }
  .viz-frame.context, .viz-frame.hodograph { height: 650px; }
  .viz-frame.electricity, .viz-frame.relationships, .viz-frame.profile,
  .viz-frame.time-pressure, .viz-frame.radar, .viz-frame.synoptic,
  .viz-frame.physical-energy { height: 760px; }
  .help-panel { left: auto; right: -8px; }
}
"""


def _fmt(value: float, digits: int = 1) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _fmt_grouped(value: float, digits: int = 0) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:,.{digits}f}"


def _copy_assets(figure_paths: dict[str, Path], site_dir: Path) -> dict[str, str]:
    assets_dir = site_dir / "assets"
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    relative: dict[str, str] = {}
    for name, source in figure_paths.items():
        target = assets_dir / source.name
        shutil.copy2(source, target)
        relative[name] = f"assets/{target.name}"
    return relative


def _navigation(active: str) -> str:
    links = []
    for filename, label in PAGES:
        current = ' aria-current="page"' if filename == active else ""
        links.append(f'<a href="{filename}"{current}>{html.escape(label)}</a>')
    return (
        '<div class="nav-wrap"><a class="brand" href="index.html">Atlas</a>'
        f'<nav class="primary-nav" aria-label="Primary">{"".join(links)}</nav></div>'
    )


def _plot_section(
    title: str,
    path: str,
    frame_title: str,
    help_text: str,
    frame_class: str = "",
    note: str = "",
) -> str:
    classes = f"viz-frame {frame_class}".strip()
    source_note = f'  <p class="source-note">{html.escape(note)}</p>\n' if note else ""
    return f"""
<section class="plot-section">
  <div class="section-heading">
    <h2>{html.escape(title)}</h2>
    <details class="plot-help">
      <summary aria-label="How to read {html.escape(title)}"><span aria-hidden="true">i</span></summary>
      <div class="help-panel">{html.escape(help_text)}</div>
    </details>
  </div>
{source_note}
  <div class="viz-scroll">
    <iframe class="{classes}" src="{html.escape(path)}" title="{html.escape(frame_title)}" loading="lazy" scrolling="no"></iframe>
  </div>
</section>
"""


def _page_document(
    config: AtlasConfig,
    active: str,
    page_name: str,
    description: str,
    content: str,
    updated: str,
) -> str:
    title = config.project.name if active == "index.html" else f"{page_name} | {config.project.name}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <meta name="description" content="{html.escape(description)}">
  <style>{SHARED_CSS}</style>
</head>
<body>
  <header class="site-header">{_navigation(active)}</header>
  <main><div class="page-shell">{content}</div></main>
  <footer><div class="footer-wrap">Last updated {updated}. Debrecen weather with Hungary-wide electricity context.</div></footer>
</body>
</html>
"""


def _page_intro(title: str, description: str, eyebrow: str) -> str:
    return f"""
<header class="page-intro">
  <div class="eyebrow">{html.escape(eyebrow)}</div>
  <h1>{html.escape(title)}</h1>
  <p>{html.escape(description)}</p>
</header>
"""


def archive_site(site_dir: Path, archive_dir: Path) -> Path:
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    for name in ["assets", "data"]:
        source = site_dir / name
        if source.exists():
            shutil.copytree(source, archive_dir / name)
    for source in site_dir.glob("*.html"):
        shutil.copy2(source, archive_dir / source.name)
    return archive_dir / "index.html"


def build_site(
    config: AtlasConfig,
    period_start: str,
    period_end: str,
    current_metrics: dict[str, float],
    baseline_metrics: dict[str, float],
    anomalies: list[Anomaly],
    energy: EnergyIndex,
    electricity: ElectricitySummary,
    electricity_notes: list[str],
    profile: ModelProfile,
    station: StationObservations,
    radar: RadarArchive,
    lightning: LightningArchive,
    fronts: FrontAnalysis,
    analogs: AnalogAnalysis,
    synoptic: SynopticArchive,
    physical_energy: PhysicalEnergy,
    regime: RegimeClassification,
    figure_paths: dict[str, Path],
    processed_paths: dict[str, Path],
    site_dir: Path | None = None,
    quality_notes: list[str] | None = None,
) -> Path:
    site_dir = site_dir or config.outputs.site_dir
    site_dir.mkdir(parents=True, exist_ok=True)
    figures = _copy_assets(figure_paths, site_dir)

    data_dir = site_dir / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    data_links: dict[str, str] = {}
    for name, source in processed_paths.items():
        target = data_dir / source.name
        shutil.copy2(source, target)
        data_links[name] = f"data/{target.name}"

    payload: dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
        "current_metrics": current_metrics,
        "baseline_metrics": baseline_metrics,
        "energy": asdict(energy),
        "electricity": asdict(electricity),
        "model_profile": {
            "valid_time": profile.valid_time.isoformat() if profile.valid_time is not None else None,
            "source": profile.source,
            "diagnostics": profile.diagnostics,
            "notes": profile.notes,
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
                float(radar.timeline["domain_max_dbz"].max()) if not radar.timeline.empty else None
            ),
            "notes": radar.notes,
        },
        "lightning": {
            "events": len(lightning.frame),
            "closest_event_km": (
                float(lightning.frame["distance_km"].min()) if not lightning.frame.empty else None
            ),
            "notes": lightning.notes,
        },
        "frontal_passages": [
            {**asdict(event), "time": event.time.isoformat()} for event in fronts.events
        ],
        "historical_analogs": [asdict(match) for match in analogs.matches],
        "analog_notes": analogs.notes,
        "synoptic": {"frames": len(synoptic.times), "notes": synoptic.notes},
        "physical_energy": {
            "pv_yield_kwh_per_kwp": physical_energy.pv_yield_kwh_per_kwp,
            "pv_capacity_factor_pct": physical_energy.pv_capacity_factor_pct,
            "wind_full_load_hours": physical_energy.wind_full_load_hours,
            "wind_capacity_factor_pct": physical_energy.wind_capacity_factor_pct,
            "mean_wind_power_density_w_m2": physical_energy.mean_wind_power_density_w_m2,
            "notes": physical_energy.notes,
        },
        "regime": asdict(regime),
        "anomalies": [asdict(item) for item in anomalies],
        "quality_notes": quality_notes or [],
    }
    (data_dir / "summary.json").write_text(
        json.dumps(json_ready(payload), indent=2, allow_nan=False), encoding="utf-8"
    )

    period_label = f"{config.location.name}, {config.location.region} - {period_start} to {period_end}"
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    observed_temp = float(pd.to_numeric(station.frame.get("temperature_c"), errors="coerce").mean()) if not station.frame.empty else float("nan")
    observed_rain = float(pd.to_numeric(station.frame.get("precipitation_mm"), errors="coerce").sum()) if not station.frame.empty else float("nan")
    observed_gust = float(pd.to_numeric(station.frame.get("wind_gust_ms"), errors="coerce").max()) if not station.frame.empty else float("nan")
    radar_max = float(radar.timeline["domain_max_dbz"].max()) if not radar.timeline.empty else float("nan")
    lightning_count = len(lightning.frame)
    closest_flash = float(lightning.frame["distance_km"].min()) if not lightning.frame.empty else float("nan")
    best_analog = analogs.matches[0] if analogs.matches else None
    cape = profile.diagnostics.get("surface_based_cape_j_kg", float("nan"))
    pbl = profile.diagnostics.get("boundary_layer_height_m", float("nan"))

    overview = f"""
<header class="hero">
  <div>
    <div class="eyebrow">{html.escape(period_label)}</div>
    <h1>{html.escape(config.project.name)}</h1>
    <p class="hero-regime">{html.escape(regime.label)}</p>
    <p class="brief">{html.escape(regime.briefing)}</p>
    <p class="meta">{html.escape(config.project.tagline)}</p>
  </div>
  <div class="summary" aria-label="Renewable weather scores">
    <div class="score"><span>PV yield</span><strong>{_fmt(physical_energy.pv_yield_kwh_per_kwp, 1)}</strong><span>kWh per installed kWp</span></div>
    <div class="score"><span>Wind full-load hours</span><strong>{_fmt(physical_energy.wind_full_load_hours, 1)}</strong><span>generic 100 m turbine</span></div>
    <div class="score"><span>Combined weather score</span><strong>{_fmt(energy.combined_score, 0)}</strong><span>{html.escape(energy.label)}</span></div>
  </div>
</header>
<p class="analysis-lead"><strong>The report in brief.</strong> {html.escape(regime.briefing)} Atlas found {len(fronts.events)} objective frontal passage candidate(s), {lightning_count:,} lightning event(s) within {config.hungaromet.lightning_radius_km:.0f} km, and a maximum sampled radar reflectivity of {_fmt(radar_max)} dBZ.</p>
<div class="insight-grid">
  <article class="insight"><span class="provenance">Observed</span><h3>Debrecen Airport</h3><p>Mean {_fmt(observed_temp)} C, {_fmt(observed_rain)} mm precipitation and a peak gust of {_fmt(observed_gust)} m/s from station {station.station_id}.</p></article>
  <article class="insight"><span class="provenance">Radar + LINET</span><h3>Storm character</h3><p>{lightning_count:,} lightning events were inside the study radius; the closest was {_fmt(closest_flash)} km from Debrecen.</p></article>
  <article class="insight"><span class="provenance">Model-derived</span><h3>Atmospheric column</h3><p>Selected-profile surface-based CAPE was {_fmt(cape, 0)} J/kg and boundary-layer height was {_fmt(pbl, 0)} m.</p></article>
  <article class="insight"><span class="provenance">ERA5 analog</span><h3>Historical likeness</h3><p>{html.escape(best_analog.start_date + ' to ' + best_analog.end_date + ': ' + best_analog.character) if best_analog else 'No robust seasonal analog was available.'}</p></article>
</div>
"""
    overview += _plot_section(
        "Annotated 72-Hour Meteogram",
        figures["meteogram"],
        "Interactive rolling three-day meteogram with frontal annotations",
        "Read downward through temperature and dew point, pressure, wind and gusts, precipitation, then cloud and radiation. Red vertical markers identify objective frontal-passage candidates.",
        "meteogram",
    )

    weather = _page_intro(
        "Weather Analysis",
        "Observed conditions at Debrecen Airport, their relationship to the gridded record, and the synoptic environment in which the period evolved.",
        period_label,
    )
    weather += f'<p class="analysis-lead"><strong>Observation first.</strong> Station {station.station_id} recorded a mean temperature of {_fmt(observed_temp)} C, {_fmt(observed_rain)} mm of precipitation and a maximum gust of {_fmt(observed_gust)} m/s. Dotted lines in the comparison are gridded context, not observations.</p>'
    weather += _plot_section(
        "Debrecen Airport Observation Ledger",
        figures["station_comparison"],
        "HungaroMet station observations compared with gridded weather",
        "Solid traces are HungaroMet 10-minute station observations aggregated hourly. Dotted traces are the gridded series used for climatological continuity; differences expose representativeness and model-analysis error.",
        "electricity",
        "Observed at HungaroMet station 64711, Debrecen Airport.",
    )
    weather += _plot_section(
        "Synoptic Evolution",
        figures["synoptic_evolution"],
        "Animated Central European synoptic analysis",
        "Filled contours show 850 hPa temperature, solid contours sea-level pressure, and dashed contours 500 hPa geopotential height. Animate the sequence to follow air-mass and circulation changes around Debrecen.",
        "synoptic",
    )
    weather += _plot_section("Wind Regime", figures["wind_rose"], "Interactive wind rose", "Spokes point toward the direction the wind came from. Length is frequency and color separates speed classes.", "context")
    weather += _plot_section("Pressure And Frontal Tendency", figures["pressure_tendency"], "Interactive pressure tendency", "Six-hour pressure changes expose troughs, frontal passages and the establishment or breakdown of anticyclonic conditions.", "context")

    event_items = []
    for event in fronts.events:
        local_event = event.time.tz_convert(config.location.timezone)
        event_items.append(f'<li><div class="event-time">{local_event.strftime("%d %b %H:%M %Z")}</div><div class="event-copy"><strong>{html.escape(event.kind)} - {event.confidence:.0%} confidence</strong><p>{html.escape(event.briefing)}</p></div></li>')
    if not lightning.hourly.empty:
        peak = lightning.hourly.loc[lightning.hourly["flash_count"].idxmax()]
        peak_time = pd.Timestamp(peak["time"]).tz_convert(config.location.timezone)
        event_items.append(f'<li><div class="event-time">{peak_time.strftime("%d %b %H:%M %Z")}</div><div class="event-copy"><strong>Peak lightning hour</strong><p>{int(peak["flash_count"]):,} LINET events occurred within the configured Debrecen radius.</p></div></li>')
    if not event_items:
        event_items.append('<li><div class="event-time">Entire period</div><div class="event-copy"><strong>No dominant storm or frontal event</strong><p>The objective detectors found no sufficiently coherent event signature.</p></div></li>')
    storms = _page_intro("Storm And Front Diary", "A chronological reconstruction using radar, lightning and rapid surface changes rather than precipitation totals alone.", period_label)
    storms += f'<p class="analysis-lead"><strong>Event diagnosis.</strong> Radar reached {_fmt(radar_max)} dBZ in the sampled domain. LINET registered {lightning_count:,} events within {config.hungaromet.lightning_radius_km:.0f} km, while the surface detector identified {len(fronts.events)} frontal candidate(s).</p><section class="content-section"><h2>Event chronology</h2><ul class="event-list">{"".join(event_items)}</ul></section>'
    storms += _plot_section("Radar Replay And Accumulation", figures["radar_archive"], "Animated radar replay and accumulation proxy", "Play the sampled reflectivity sequence on the left. The right panel integrates a standard Z-R conversion and is an approximate spatial precipitation proxy, not a gauge-adjusted accumulation product.", "radar")
    storms += _plot_section("Lightning Diary", figures["lightning_diary"], "LINET lightning map and hourly diary", "Point color shows peak-current polarity and magnitude, point size scales with absolute current, and the hourly histogram reveals convective timing.", "context")

    profile_note = "Model-derived near Debrecen; parcel quantities use MetPy and are not observed radiosonde values."
    diagnostic_cells = [
        ("SB CAPE", profile.diagnostics.get("surface_based_cape_j_kg"), "J/kg"),
        ("SB CIN", profile.diagnostics.get("surface_based_cin_j_kg"), "J/kg"),
        ("LCL", profile.diagnostics.get("lcl_height_m_asl"), "m ASL"),
        ("PWAT", profile.diagnostics.get("precipitable_water_mm"), "mm"),
        ("Wet-bulb zero", profile.diagnostics.get("wet_bulb_zero_m_asl"), "m ASL"),
        ("PBL height", profile.diagnostics.get("boundary_layer_height_m"), "m"),
        ("Ventilation", profile.diagnostics.get("ventilation_index_m2_s"), "m2/s"),
        ("Freezing level", profile.diagnostics.get("freezing_level_m_asl"), "m ASL"),
    ]
    ledger = "".join(f'<div><span>{html.escape(label)}</span><strong>{_fmt(value, 0)} {html.escape(unit)}</strong></div>' for label, value, unit in diagnostic_cells)
    upper_air = _page_intro("Atmospheric Column", "Thermodynamic structure, parcel behavior, wind shear and boundary-layer evolution through the complete 72-hour period.", period_label)
    upper_air += f'<p class="analysis-lead"><strong>Selected profile.</strong> CAPE {_fmt(cape, 0)} J/kg, precipitable water {_fmt(profile.diagnostics.get("precipitable_water_mm", float("nan")), 0)} mm and wet-bulb-zero height {_fmt(profile.diagnostics.get("wet_bulb_zero_m_asl", float("nan")), 0)} m ASL.</p><div class="diagnostic-ledger">{ledger}</div>'
    upper_air += _plot_section("Model Skew-T", figures["model_profile"], "Interactive Skew-T-style model atmospheric profile", "Temperature, dew point and wind are plotted on pressure surfaces. The ledger adds parcel-derived CAPE, CIN, LCL, LFC, equilibrium level and precipitable water where calculable.", "profile", profile_note)
    upper_air += _plot_section("Hodograph", figures["hodograph"], "Interactive hodograph and bulk wind shear", "The curve traces horizontal wind components with height. Length shows speed shear, curvature shows directional turning, and the inset reports layer bulk shear.", "hodograph", profile_note)
    upper_air += _plot_section("Parcel And Boundary-Layer Evolution", figures["column_diagnostics"], "Parcel and boundary-layer time series", "CAPE and CIN show buoyancy, PBL height shows mixing depth, total-column water tracks moisture availability, and freezing-level evolution constrains precipitation phase and hail melting.", "physical-energy", profile_note)
    upper_air += _plot_section("Time-Pressure Curtain", figures["time_pressure"], "Interactive time-pressure atmospheric curtain", "Time runs left to right and pressure decreases upward. Switch among humidity, temperature anomaly and wind speed to diagnose layer evolution and frontal depth.", "time-pressure", "A Debrecen time-pressure diagnostic adapted from a Hovmoller layout.")

    analog_rows = "".join(
        f'<div class="analog-row"><strong>{html.escape(match.start_date)} to {html.escape(match.end_date)}</strong><span>{match.similarity:.0f}% similarity</span><div>{html.escape(match.character)}; {_fmt(match.metrics.get("temperature_mean_c", float("nan")))} C, {_fmt(match.metrics.get("precipitation_total_mm", float("nan")))} mm and {_fmt(match.metrics.get("wind_speed_10m_mean_ms", float("nan")))} m/s mean 10 m wind.</div></div>'
        for match in analogs.matches
    ) or '<p>No robust historical analogs were available.</p>'
    climate = _page_intro("Debrecen Climate Context", "The current period placed inside its season, recent weekly evolution and closest historical weather analogs.", period_label)
    climate += f'<p class="analysis-lead"><strong>Historical likeness.</strong> {html.escape(best_analog.start_date + " to " + best_analog.end_date) + " was the closest match, described as " + html.escape(best_analog.character) + "." if best_analog else "No robust analog could be selected."}</p><section class="content-section"><h2>Closest seasonal analogs</h2><div class="analog-list">{analog_rows}</div></section>'
    climate += _plot_section("Seven-Day Weather Diary", figures["seven_day_context"], "Seven-day weather context", "The highlighted final three days are the active report; the preceding four days preserve the transition into the current regime.", "context")
    climate += _plot_section("Anomaly Structure", figures["anomaly_bars"], "Weather anomaly bars", "Bars show standard deviations from the same calendar window in prior years. Sign means above or below normal, not favorable or unfavorable.")
    climate += _plot_section("Daily Regime Evolution", figures["regime_strip"], "Daily regime strip", "Each segment is one local day classified with transparent weather rules.", "compact")
    climate += _plot_section("Solar Climatology", figures["solar_diurnal"], "Solar diurnal curves", "Daily radiation profiles are compared with the historical median to distinguish clear, overcast and intermittently cloudy solar regimes.")

    electricity_page = _page_intro("Energy Weather", "Physical reference-system yields for Debrecen weather, followed by Hungary-wide measured electricity-system context.", period_label)
    electricity_page += f'<p class="analysis-lead"><strong>Weather translated into production.</strong> A fixed south-facing reference array produced an estimated {physical_energy.pv_yield_kwh_per_kwp:.1f} kWh/kWp. A generic 100 m turbine produced {physical_energy.wind_full_load_hours:.1f} full-load hours at a mean capacity factor of {physical_energy.wind_capacity_factor_pct:.1f}%.</p><div class="metric-band" aria-label="Physical and system energy summary"><div class="metric"><span>PV weather yield</span><strong>{_fmt(physical_energy.pv_yield_kwh_per_kwp, 1)}</strong><span>kWh/kWp</span></div><div class="metric"><span>Wind capacity factor</span><strong>{_fmt(physical_energy.wind_capacity_factor_pct, 1)}</strong><span>percent</span></div><div class="metric"><span>Hungary average load</span><strong>{_fmt_grouped(electricity.average_load_mw)}</strong><span>MW</span></div><div class="metric"><span>Day-ahead price</span><strong>{_fmt(electricity.average_price_eur_mwh, 0)}</strong><span>EUR/MWh</span></div></div>'
    electricity_page += _plot_section("Physical PV And Wind Yield", figures["physical_energy"], "Physically based renewable weather yield", "PV uses solar position, plane-of-array irradiance and cell-temperature derating. Wind uses 100 m speed, moist-air density and a generic turbine power curve.", "physical-energy")
    electricity_page += _plot_section("Solar-Wind Weather Quadrant", figures["energy_quadrant"], "Solar and wind potential quadrant", "The indices provide a normalized climatological view; the physical-yield panel above provides the engineering interpretation.", "context")
    electricity_page += _plot_section("Hungary Electricity Context", figures["electricity_overview"], "Hungary electricity system overview", "Compare national load, residual load, generation and price with the local Debrecen weather chronology.", "electricity", "Energy-Charts and ENTSO-E are Hungary-wide context, not Debrecen metering.")
    electricity_page += _plot_section("Weather-Electricity Relationships", figures["weather_electricity_links"], "Weather and electricity relationships", "Hourly associations are diagnostic and do not establish causality or represent a plant-level power forecast.", "relationships")

    anomalies_rows = "\n".join(
        f"<tr><th>{html.escape(item.label)}</th><td>{_fmt(item.value)}</td><td>{_fmt(item.baseline_mean)}</td>"
        f"<td>{item.anomaly:+.1f} {html.escape(item.unit)}</td><td>{_fmt(item.percentile, 0)}th</td></tr>"
        for item in anomalies
    )
    signal_items = "\n".join(f"<li>{html.escape(signal)}</li>" for signal in regime.signals)
    quality_items = "\n".join(f"<li>{html.escape(note)}</li>" for note in (quality_notes or []))
    electricity_note_items = "\n".join(f"<li>{html.escape(note)}</li>" for note in electricity_notes)
    profile_note_items = "\n".join(f"<li>{html.escape(note)}</li>" for note in profile.notes)
    expert_note_items = "\n".join(
        f"<li>{html.escape(note)}</li>"
        for note in (
            station.notes
            + radar.notes
            + lightning.notes
            + fronts.notes
            + analogs.notes
            + synoptic.notes
            + physical_energy.notes
        )
    )
    baseline_period = processed_paths.get("baseline_metrics", Path("baseline_metrics.csv")).name
    downloads = [
        ("Current weather observations", data_links.get("current_hourly")),
        ("Seven-day weather context", data_links.get("seven_day_context_hourly")),
        ("Period metrics", data_links.get("period_metrics")),
        ("Baseline metrics", data_links.get("baseline_metrics")),
        ("Weather anomalies", data_links.get("anomalies")),
        ("Electricity time series", data_links.get("electricity")),
        ("Selected model profile", data_links.get("model_profile")),
        ("Full profile time series", data_links.get("model_profile_series")),
        ("Parcel and boundary-layer series", data_links.get("model_profile_surface")),
        ("HungaroMet station observations", data_links.get("hungaromet_station")),
        ("Radar event timeline", data_links.get("radar_timeline")),
        ("Radar accumulation grid", data_links.get("radar_accumulation")),
        ("LINET lightning events", data_links.get("lightning")),
        ("Objective frontal passages", data_links.get("frontal_passages")),
        ("Historical analogs", data_links.get("historical_analogs")),
        ("Synoptic analysis fields", data_links.get("synoptic_fields")),
        ("Physical PV and wind yields", data_links.get("physical_energy")),
        ("Machine-readable summary", "data/summary.json"),
    ]
    download_items = "\n".join(
        f'<li><a href="{html.escape(path)}">{html.escape(label)}</a></li>'
        for label, path in downloads
        if path
    )
    methods = _page_intro(
        "Methods And Data",
        "Transparent baselines, explainable regime rules, source notes, and downloadable outputs for the current report.",
        period_label,
    )
    methods += f"""
<section class="content-section">
  <h2>Historical Percentile Ranks</h2>
  <div class="table-scroll">
    <table>
      <thead><tr><th>Metric</th><th>This period</th><th>Baseline mean</th><th>Anomaly</th><th>Percentile</th></tr></thead>
      <tbody>{anomalies_rows}</tbody>
    </table>
  </div>
</section>
<div class="methods-grid">
  <section class="content-section">
    <h2>Classification Signals</h2>
    <ul>{signal_items}</ul>
  </section>
  <section class="content-section">
    <h2>Sources And Quality</h2>
    <p>HungaroMet supplies Debrecen Airport observations, composite radar and LINET lightning. Open-Meteo supplies the continuous gridded surface record, pressure-level model fields, synoptic grid and ERA5 analog archive. The baseline uses the same three-day calendar window over the prior {config.baseline.years} years and is stored in {html.escape(baseline_period)}.</p>
    <ul>{quality_items}</ul>
    <ul>{electricity_note_items}</ul>
    <ul>{profile_note_items}</ul>
    <ul>{expert_note_items}</ul>
  </section>
</div>
<section class="content-section">
  <h2>Downloads</h2>
  <ul class="download-list">{download_items}</ul>
</section>
"""

    documents = {
        "index.html": ("Overview", "Rolling Debrecen weather and renewable-energy overview.", overview),
        "weather.html": ("Weather", "Observed and synoptic weather analysis for Debrecen.", weather),
        "storms.html": ("Storms", "Radar, lightning and frontal-event reconstruction for Debrecen.", storms),
        "upper-air.html": ("Upper Air", "Parcel, boundary-layer and atmospheric-profile diagnostics over Debrecen.", upper_air),
        "climate.html": ("Climate", "Historical analogs and climatological context for Debrecen.", climate),
        "energy.html": ("Energy", "Physical renewable yields and Hungary electricity context.", electricity_page),
        "methods.html": ("Methods", "Atlas methods, sources, quality notes, and data downloads.", methods),
    }
    for filename, (page_name, description, content) in documents.items():
        target = site_dir / filename
        target.write_text(
            _page_document(config, filename, page_name, description, content, updated),
            encoding="utf-8",
        )

    return site_dir / "index.html"
