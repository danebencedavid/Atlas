from __future__ import annotations

import html
import json
import re
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from atlas.activity_lenses import ACTIVITY_LENS_SCHEMA
from atlas.activity_lenses import available_lens_ids
from atlas.almanac import Almanac, PeriodClimate, RecordEntry
from atlas.analogs import AnalogAnalysis
from atlas.anomalies import Anomaly
from atlas.archive_figures import publish_shared_figure_stubs
from atlas.archive_figures import write_shared_figure_renderer
from atlas.archive_bundle import archive_size_report
from atlas.archive_bundle import build_archive_catalog
from atlas.archive_bundle import ensure_edition_bundle
from atlas.archive_bundle import ImmutableEditionError
from atlas.archive_bundle import validate_edition_bundle
from atlas.archive_styles import externalize_repeated_archive_styles
from atlas.archive_publish import enforce_published_archive_limits
from atlas.archive_publish import staged_directory
from atlas.climatology import ClimateReference
from atlas.config import AtlasConfig
from atlas.electricity import ElectricitySummary
from atlas.energy import EnergyIndex, PhysicalEnergy
from atlas.errata import annotate_daily_from_periods
from atlas.fronts import FrontAnalysis
from atlas.hungaromet import LightningArchive, RadarArchive, StationObservations
from atlas.kinematics import StormKinematics
from atlas.land import LandSurfaceAnalysis
from atlas.phenomena import PhenomenaAnalysis, WeatherPhenomenon
from atlas.profile import ModelProfile
from atlas.quality import InputCoverage
from atlas.radar_cells import RadarCellAnalysis
from atlas.regimes import RegimeClassification
from atlas.satellite import SatelliteArchive
from atlas.serialization import json_ready
from atlas.story import WeatherStory, build_weather_story
from atlas.synoptic import SynopticArchive
from atlas.trajectory import AirMassOrigin
from atlas.verification import StationVerification
from atlas.attribution import SOURCE_ATTRIBUTION_HTML


PUBLIC_PAGES = (
    ("report.html", "Overview"),
    ("weather.html", "Weather"),
    ("events.html", "Events"),
    ("energy.html", "Energy"),
    ("context.html", "Climate Context"),
    ("methods.html", "Methods"),
)

ANALYSIS_PAGES = (
    ("index.html", "Overview"),
    ("story.html", "Weather Story"),
    ("surface-synoptic.html", "Surface & Synoptic"),
    ("storms-satellite.html", "Storms & Satellite"),
    ("upper-air.html", "Upper Air & Dynamics"),
    ("climate.html", "Climate & Analogs"),
    ("land-energy.html", "Land Surface & Energy"),
    ("methods.html", "Methods & Evidence"),
)

ARCHIVED_PUBLIC_PAGES = (
    ("index.html", "Overview"),
    ("weather.html", "Weather"),
    ("events.html", "Events"),
    ("energy.html", "Energy"),
    ("context.html", "Climate Context"),
    ("methods.html", "Methods"),
)

LEGACY_ANALYSIS_PAGES = (
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
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.skip-link {
  position: fixed;
  top: 8px;
  left: 8px;
  z-index: 100;
  padding: 9px 12px;
  color: #ffffff;
  background: var(--ink);
  border-radius: 4px;
  transform: translateY(-160%);
}
.skip-link:focus { transform: translateY(0); }
:where(a, button, input, select, summary, [tabindex]):focus-visible {
  outline: 3px solid var(--blue);
  outline-offset: 3px;
}
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
.edition-notice {
  border-bottom: 1px solid #f0cf78;
  background: #fff8dc;
  color: #654b08;
  font-size: 0.86rem;
  font-weight: 650;
  text-align: center;
  padding: 9px 24px;
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
.report-switch {
  display: flex;
  flex: 0 0 auto;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
}
.report-switch a {
  padding: 7px 10px;
  color: #475467;
  background: #ffffff;
  font-size: 0.78rem;
  font-weight: 750;
  text-decoration: none;
  white-space: nowrap;
}
.report-switch a + a { border-left: 1px solid var(--line); }
.report-switch a[aria-current="true"] { color: #ffffff; background: var(--ink); }
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
  height: 728px;
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
.viz-frame.meteogram { height: 1088px; }
.viz-frame.context { height: 828px; }
.viz-frame.electricity { height: 928px; }
.viz-frame.relationships { height: 888px; }
.viz-frame.profile, .viz-frame.time-pressure { height: 928px; }
.viz-frame.hodograph { height: 868px; }
.viz-frame.radar, .viz-frame.synoptic, .viz-frame.physical-energy { height: 868px; }
.viz-frame.satellite { height: 948px; }
.viz-frame.land-surface { height: 1028px; }
.viz-frame.climate-reference { height: 888px; }
.viz-frame.phenomena { height: 648px; }
.viz-frame.compact { height: 368px; }
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
.evidence-meta { margin-top: 5px; color: var(--muted); font-size: 0.82rem; }
.public-lead { max-width: 850px; font-size: 1.18rem; color: #344054; }
.public-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.public-facts div { padding: 18px; border-right: 1px solid var(--line); }
.public-facts div:last-child { border-right: 0; }
.public-facts span { display: block; color: var(--muted); font-size: .82rem; }
.public-facts strong { display: block; margin-top: 3px; font-size: 1.3rem; }
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
  gap: 0;
  padding: 0;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
  list-style: none;
}
.download-list li {
  min-width: 0;
  border-bottom: 1px solid var(--line);
}
.download-list li:nth-child(odd) { border-right: 1px solid var(--line); }
.download-list li:last-child,
.download-list li:nth-last-child(2):nth-child(odd) { border-bottom: 0; }
.download-list a {
  min-height: 62px;
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  color: var(--ink);
  text-decoration: none;
}
.download-list a:hover { background: var(--rail, var(--paper)); }
.download-filemark {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  color: var(--muted);
  background: var(--rail, var(--paper));
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 14px;
}
.download-copy { min-width: 0; }
.download-copy strong,
.download-copy small { display: block; }
.download-copy strong {
  overflow: hidden;
  font-size: 0.88rem;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.download-copy small {
  margin-top: 2px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.68rem;
  text-transform: uppercase;
}
.download-action {
  color: var(--muted);
  font-size: 0.74rem;
  font-weight: 600;
}
.download-list a:hover .download-action { color: var(--blue); }
.downloads-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 13px;
}
.downloads-heading h2 { margin-bottom: 3px; }
.downloads-heading p { margin: 0; color: var(--muted); font-size: 0.82rem; }
.download-count {
  flex: 0 0 auto;
  padding: 3px 7px;
  color: var(--muted);
  background: var(--rail, var(--paper));
  border: 1px solid var(--line);
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.68rem;
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
@media (max-width: 1400px) and (min-width: 861px) {
  .nav-wrap { padding-top: 8px; flex-wrap: wrap; gap: 0 24px; }
  .primary-nav {
    order: 3;
    flex: 1 0 100%;
    width: 100%;
    overflow: visible;
    flex-wrap: wrap;
  }
  .primary-nav a { min-height: 48px; }
}
@media (max-width: 860px) {
  .nav-wrap { padding: 8px 18px 0; gap: 8px 16px; flex-wrap: wrap; }
  .primary-nav { order: 3; flex: 1 0 100%; width: 100%; }
  .primary-nav a { min-height: 48px; }
  .hero { grid-template-columns: 1fr; min-height: 0; padding-top: 10px; }
  .page-shell { padding: 24px 18px 40px; }
  .summary, .metric-band, .methods-grid, .download-list, .insight-grid, .public-facts,
  .diagnostic-ledger { grid-template-columns: 1fr; }
  .download-list li:nth-child(odd) { border-right: 0; }
  .download-list li:nth-last-child(2):nth-child(odd) { border-bottom: 1px solid var(--line); }
  .download-list li:last-child { border-bottom: 0; }
  .downloads-heading { align-items: flex-start; }
  .insight, .insight:nth-child(2n), .insight:nth-last-child(-n+2),
  .diagnostic-ledger div { border-right: 0; border-bottom: 1px solid var(--line); }
  .insight:last-child, .diagnostic-ledger div:last-child { border-bottom: 0; }
  .event-list li, .analog-row { grid-template-columns: 1fr; gap: 4px; }
  .metric { border-right: 0; border-bottom: 1px solid var(--line); }
  .metric:last-child { border-bottom: 0; }
  h1 { font-size: 3.5rem; }
  .viz-frame { height: 658px; }
  .viz-frame { min-width: 720px; }
  .viz-frame.compact { min-width: 520px; }
  .viz-frame.meteogram { height: 1028px; }
  .viz-frame.context, .viz-frame.hodograph { height: 738px; }
  .viz-frame.electricity, .viz-frame.relationships, .viz-frame.profile,
  .viz-frame.time-pressure, .viz-frame.radar, .viz-frame.synoptic,
  .viz-frame.physical-energy { height: 848px; }
  .viz-frame.satellite, .viz-frame.land-surface { height: 908px; }
  .help-panel { left: auto; right: -8px; }
}
"""


DATA_FIRST_CSS = """
:root {
  --ink: #232323;
  --ink-soft: #50504d;
  --muted: #66645f;
  --line: #e7e7e3;
  --line-strong: #d8d8d3;
  --paper: #ffffff;
  --panel: #ffffff;
  --canvas: #ffffff;
  --rail: #f6f6f4;
  --hover: #ebebe8;
  --selected: #e7e7e3;
  --blue: #315f8d;
  --blue-soft: #eaf1f7;
  --green: #2f6f58;
  --gold: #8a5b16;
  --red: #a83b33;
  --sidebar: 208px;
  --topbar: 48px;
}
body {
  color: var(--ink);
  background: var(--canvas);
  font-size: 14px;
}
a { color: inherit; }
.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: var(--sidebar) minmax(0, 1fr);
}
.workspace { min-width: 0; }
.site-header {
  position: sticky;
  top: 0;
  z-index: 30;
  height: 100vh;
  background: var(--rail);
  border-right: 1px solid var(--line-strong);
  border-bottom: 0;
  backdrop-filter: none;
}
.nav-wrap {
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 8px;
  display: flex;
  flex-direction: column;
  flex-wrap: nowrap;
  align-items: stretch;
  gap: 0;
}
.brand {
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 6px 8px;
  color: var(--ink);
  border-radius: 5px;
  font-size: 13px;
  font-weight: 650;
}
.brand::before {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  color: #fff;
  background: var(--ink);
  border-radius: 4px;
  content: "A";
  font-family: Georgia, serif;
  font-size: 14px;
}
.brand:hover { background: var(--hover); }
.nav-label {
  display: block;
  margin: 17px 8px 5px;
  color: #969692;
  font-size: 11px;
  font-weight: 600;
}
.report-switch {
  display: grid;
  gap: 2px;
  margin: 0;
  border: 0;
  border-radius: 0;
  overflow: visible;
}
.report-switch a {
  min-height: 30px;
  display: flex;
  align-items: center;
  padding: 5px 8px;
  color: var(--ink-soft);
  background: transparent;
  border: 0;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 500;
}
.report-switch a + a { border-left: 0; }
.report-switch a:hover { background: var(--hover); }
.report-switch a[aria-current="true"] {
  color: var(--ink);
  background: var(--selected);
}
.primary-nav {
  display: flex;
  flex-direction: column;
  flex: 0 0 auto;
  order: initial;
  align-items: stretch;
  gap: 2px;
  width: auto;
  min-width: 0;
  overflow: visible;
  flex-wrap: nowrap;
}
.primary-nav a {
  min-height: 30px;
  display: flex;
  align-items: center;
  padding: 5px 8px;
  color: var(--ink-soft);
  border: 0;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 450;
}
.primary-nav a:hover { color: var(--ink); background: var(--hover); }
.primary-nav a[aria-current="page"] {
  color: var(--ink);
  background: var(--selected);
  border-bottom-color: transparent;
  font-weight: 600;
}
/* The report card action follows the same restrained paper-and-ink treatment as
   the publication links above it. */
.share-day-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin: 0 auto;
  padding: 8px 14px;
  color: var(--ink);
  background: rgba(255,255,255,.65);
  border: 1px solid var(--line-strong);
  border-radius: 5px;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}
.share-day-button span { color: var(--blue); font-size: 13px; }
.share-day-button:hover { background: var(--hover); border-color: var(--muted); }
.share-day-button[aria-expanded="true"] { background: var(--selected); border-color: var(--muted); }
/* Sits apart from the navigation groups above it, with the button centred rather
   than stretched across the sidebar. */
.share-wrap {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 30px 4px 0;
}
.share-menu {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 40;
  display: grid;
  gap: 4px;
  margin-top: 6px;
  padding: 10px;
  background: #ffffff;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  box-shadow: 0 12px 30px rgba(15,23,42,.18);
}
.share-menu-title {
  margin: 0 0 4px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.4;
}
.share-menu-title strong { display: block; color: var(--ink); font-size: 11px; }
.share-menu-label {
  margin: 6px 0 2px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
  text-transform: none;
}
.share-menu-primary,
.share-menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 6px;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}
/* Ink rather than colour carries the primary action, the same way the report switch
   marks its current edition. */
.share-menu-primary {
  color: var(--canvas);
  background: var(--ink);
  border-color: var(--ink);
}
.share-menu-primary span { color: rgba(255,255,255,.62); font-size: 11px; font-weight: 500; }
.share-menu-item:hover { background: var(--hover); }
.share-menu-primary:hover { background: var(--ink-soft); border-color: var(--ink-soft); }
.share-menu-links { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; }
.share-menu-url {
  width: 100%;
  margin-top: 4px;
  padding: 7px 8px;
  color: var(--ink);
  background: var(--rail);
  border: 1px solid var(--line-strong);
  border-radius: 5px;
  font: inherit;
  font-size: 11px;
}
.share-menu-links .share-menu-item { justify-content: center; padding: 8px 4px; font-size: 11px; }
.share-day-button:disabled {
  cursor: not-allowed;
  background: var(--rail);
  border-color: var(--line);
  color: var(--muted);
}
.share-day-button:disabled span { color: var(--muted); }
.sidebar-note {
  margin: auto 4px 2px;
  padding: 10px;
  color: var(--muted);
  background: rgba(255,255,255,.55);
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  font-size: 11px;
  line-height: 1.4;
}
.sidebar-note strong {
  display: block;
  margin-bottom: 3px;
  color: var(--ink-soft);
  font-size: 11px;
}
.report-topbar {
  position: sticky;
  top: 0;
  z-index: 25;
  height: var(--topbar);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 18px;
  background: rgba(255,255,255,.94);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(10px);
}
.menu-button {
  width: 28px;
  height: 28px;
  display: none;
  place-items: center;
  padding: 0;
  color: var(--muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 5px;
  cursor: pointer;
}
.menu-button:hover { background: var(--hover); }
.breadcrumbs {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--muted);
  font-size: 12px;
}
.breadcrumbs span, .breadcrumbs strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.breadcrumbs strong { color: var(--ink-soft); font-weight: 550; }
.sidebar-scrim { display: none; }
.edition-notice {
  padding: 8px 20px;
  color: #71541b;
  background: #f7efdf;
  border-bottom: 1px solid #e5d5b5;
  font-size: 11px;
  font-weight: 550;
}
.page-shell {
  width: min(100%, 1320px);
  margin: 0 auto;
  padding: 34px 48px 72px;
}
.page-shell.with-outline { width: min(100%, 1480px); }
.page-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 184px;
  gap: 56px;
  align-items: start;
}
.page-body { min-width: 0; }
.page-body h2[id] { scroll-margin-top: calc(var(--topbar) + 22px); }
.page-outline { min-width: 0; }
.page-outline nav {
  position: sticky;
  top: calc(var(--topbar) + 24px);
  display: grid;
  gap: 2px;
  padding-left: 13px;
  border-left: 1px solid var(--line-strong);
}
.page-outline strong {
  margin-bottom: 5px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
}
.page-outline a {
  padding: 4px 7px;
  color: var(--muted);
  border-radius: 4px;
  font-size: 11px;
  line-height: 1.35;
  text-decoration: none;
}
.page-outline a:hover { color: var(--ink); background: var(--hover); }
.page-outline a.current { color: var(--ink); font-weight: 600; }
.hero {
  min-height: 0;
  display: block;
  padding: 0 0 12px;
}
.eyebrow {
  margin-bottom: 7px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
  text-transform: none;
}
h1 {
  margin: 0 0 8px;
  font-size: 31px;
  font-weight: 620;
  line-height: 1.2;
}
h2 { font-size: 19px; font-weight: 620; }
.hero-regime {
  margin: 0 0 5px;
  font-size: 15px;
  font-weight: 650;
}
.brief {
  max-width: 940px;
  margin: 0;
  color: var(--ink-soft);
  font-size: 14px;
  line-height: 1.62;
}
.meta { margin: 9px 0 0; font-size: 11px; }
.publication-state {
  display: grid;
  grid-template-columns: 1.2fr 1.35fr 1.2fr 1fr;
  margin: 0 0 30px;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
}
.publication-state > div {
  min-width: 0;
  padding: 11px 16px;
  border-right: 1px solid var(--line);
}
.publication-state > div:first-child { padding-left: 0; }
.publication-state > div:last-child { padding-right: 0; border-right: 0; }
.publication-state span,
.publication-state strong,
.publication-state small { display: block; }
.publication-state span {
  margin-bottom: 2px;
  color: var(--muted);
  font-size: 11px;
}
.publication-state strong {
  overflow-wrap: anywhere;
  font-size: 12px;
  font-weight: 600;
}
.publication-state small { margin-top: 2px; color: var(--muted); font-size: 11px; }
.publication-integrity strong::before {
  width: 7px;
  height: 7px;
  display: inline-block;
  margin-right: 7px;
  background: var(--green);
  border-radius: 50%;
  content: "";
}
.publication-state[data-state="incomplete"] .publication-integrity strong { color: var(--red); }
.publication-state[data-state="incomplete"] .publication-integrity strong::before { background: var(--red); }
.source-key {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 14px 0 3px;
}
.source-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  color: var(--ink-soft);
  background: transparent;
  border: 0;
  font-size: 11px;
}
.source-chip b {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
}
.evidence-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  width: fit-content;
  padding: 2px 7px;
  color: var(--ink-soft);
  background: var(--rail);
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
}
.evidence-badge::before {
  width: 6px;
  height: 6px;
  flex: 0 0 6px;
  background: var(--muted);
  border-radius: 50%;
  content: "";
}
.evidence-badge.observed::before { background: var(--green); }
.evidence-badge.remote::before { background: var(--gold); }
.evidence-badge.model::before { background: var(--blue); }
.evidence-badge.derived::before { background: var(--red); }
.insight .evidence-badge { margin-bottom: 7px; }
.analysis-lead .evidence-badge,
.public-lead .evidence-badge { margin-right: 8px; vertical-align: 1px; }
.summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  margin-top: 24px;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
}
.score {
  min-width: 0;
  padding: 15px 18px;
  background: transparent;
  border: 0;
  border-right: 1px solid var(--line);
  border-radius: 0;
}
.score:first-child { padding-left: 0; border-top: 2px solid var(--gold); }
.score:nth-child(2) { border-top: 2px solid var(--green); }
.score:nth-child(3) { border-top: 2px solid var(--blue); }
.score:last-child { border-right: 0; }
.score strong { margin: 3px 0; font-size: 27px; font-weight: 570; }
.score span { font-size: 11px; }
.page-intro {
  max-width: 1040px;
  padding: 0 0 24px;
}
.page-intro h1 { margin-bottom: 7px; font-size: 31px; }
.page-intro p { color: var(--ink-soft); font-size: 14px; }
.home-intro {
  max-width: 980px;
  padding: 18px 0 38px;
}
.home-intro h1 {
  margin-bottom: 15px;
  font-size: 40px;
}
.home-question {
  max-width: 900px;
  margin: 0;
  color: var(--ink);
  font-family: Georgia, "Times New Roman", serif;
  font-size: 24px;
  line-height: 1.4;
}
.home-summary {
  max-width: 900px;
  margin: 18px 0 0;
  color: var(--ink-soft);
  font-size: 14px;
  line-height: 1.65;
}
.publication-ledger {
  margin-bottom: 34px;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
}
.publication-row {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr) 190px;
  gap: 24px;
  align-items: center;
  min-height: 96px;
  padding: 17px 0;
  color: inherit;
  border-bottom: 1px solid var(--line);
  text-decoration: none;
}
.publication-row:last-child { border-bottom: 0; }
.publication-row:hover { background: var(--rail); }
.publication-kind,
.publication-date {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
}
.publication-copy h2 { margin: 0 0 4px; font-size: 17px; }
.publication-copy p { margin: 0; color: var(--ink-soft); font-size: 12px; }
.publication-date { text-align: right; }
.publication-date strong {
  display: block;
  margin-top: 3px;
  color: var(--blue);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  font-size: 12px;
  font-weight: 600;
}
.home-section-lead {
  max-width: 960px;
  color: var(--ink-soft);
  font-size: 13px;
  line-height: 1.65;
}
.home-definition {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 18px;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
}
.home-definition div {
  min-width: 0;
  padding: 15px 18px;
  border-right: 1px solid var(--line);
}
.home-definition div:first-child { padding-left: 0; }
.home-definition div:last-child { border-right: 0; }
.home-definition span,
.home-definition strong { display: block; }
.home-definition span {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
}
.home-definition strong { margin-top: 4px; font-size: 13px; font-weight: 600; }
.public-facts,
.metric-band,
.diagnostic-ledger {
  border-top-color: var(--line-strong);
  border-bottom-color: var(--line-strong);
}
.public-facts { margin: 10px 0 0; }
.public-facts div { padding: 15px 18px; }
.public-facts div:first-child { padding-left: 0; border-top: 2px solid var(--red); }
.public-facts div:nth-child(2) { border-top: 2px solid var(--blue); }
.public-facts div:nth-child(3) { border-top: 2px solid var(--green); }
.public-facts strong { font-size: 24px; font-weight: 570; }
.metric { padding: 15px 18px; }
.metric strong { font-size: 24px; font-weight: 570; }
.plot-section, .content-section {
  padding: 24px 0 34px;
  border-top-color: var(--line);
}
.plot-section {
  content-visibility: auto;
  contain-intrinsic-size: auto 720px;
}
.plot-section:first-of-type { margin-top: 24px; }
.section-heading { align-items: flex-start; margin-bottom: 14px; }
.section-heading::before {
  flex: 0 0 auto;
  padding-top: 5px;
  color: #93928e;
  content: "Section";
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 650;
}
.section-heading h2 { padding-top: 0; }
.plot-help summary {
  color: var(--muted);
  background: transparent;
  border-color: var(--line-strong);
}
.help-panel { color: var(--ink-soft); border-color: var(--line-strong); }
.source-note {
  margin: -7px 0 12px 41px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
}
.figure-open {
  margin: 14px 0 0;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
}
.figure-open a { color: var(--blue); text-decoration: underline; }
.viz-scroll { border-radius: 5px; }
.viz-frame { border-color: var(--line-strong); border-radius: 5px; }
.analysis-lead,
.public-lead {
  max-width: 1040px;
  margin: 22px 0 18px;
  padding: 14px 0 14px 15px;
  color: var(--ink-soft);
  border-left: 2px solid var(--gold);
  font-size: 13px;
  line-height: 1.65;
}
.insight-grid { border-color: var(--line-strong); }
.insight { padding: 16px 18px; }
.insight .provenance, .provenance {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  text-transform: none;
}
.download-copy small { font-size: 11px; text-transform: none; }
.insight p, .event-copy p { color: var(--ink-soft); font-size: 12px; }
.activity-lenses-section {
  margin-top: 24px;
  padding: 22px 20px 24px;
  border: 1px solid var(--line-strong);
  border-top: 3px solid var(--blue);
  border-radius: 5px;
}
.activity-lenses-section .section-heading::before { display: none; }
.activity-lenses-symbol {
  position: relative;
  display: grid;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  place-items: center;
  color: var(--blue);
  background: var(--blue-soft);
  border: 1px solid var(--line-strong);
  border-radius: 50%;
}
.activity-lenses-symbol::before {
  width: 8px;
  height: 8px;
  background: var(--blue);
  border-radius: 50%;
  content: "";
}
.activity-lenses-symbol::after {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 8px;
  height: 8px;
  border: 1px solid rgba(49, 95, 141, .28);
  border-radius: 50%;
  content: "";
  animation: activity-lens-ripple 3.8s ease-out infinite;
}
@keyframes activity-lens-ripple {
  0%, 34% { opacity: 0; transform: translate(-50%, -50%) scale(1); }
  42% { opacity: .28; }
  76%, 100% { opacity: 0; transform: translate(-50%, -50%) scale(2.15); }
}
.activity-method-steps {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 18px 0 16px;
  padding: 0;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
  list-style: none;
}
.activity-method-step {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 10px;
  padding: 14px 16px;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.activity-method-step:nth-child(2n) { border-right: 0; }
.activity-method-step:nth-last-child(-n+2) { border-bottom: 0; }
.activity-method-step > span {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  color: var(--blue);
  background: var(--blue-soft);
  border-radius: 50%;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 650;
}
.activity-method-step strong { display: block; margin-bottom: 3px; font-size: 13px; }
.activity-method-step p { margin: 0; color: var(--ink-soft); font-size: 12px; line-height: 1.55; }
.activity-lens-method {
  margin: 0 0 18px;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
}
.activity-lens-method summary {
  padding: 12px 0;
  color: var(--blue);
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
}
.activity-lens-method > p {
  max-width: 980px;
  margin: 0 0 14px;
  color: var(--ink-soft);
  font-size: 12px;
  line-height: 1.6;
}
.activity-threshold-groups {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin: 0 0 16px;
}
.activity-threshold-group {
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid var(--line-strong);
  border-top: 2px solid var(--blue);
}
.activity-threshold-group h3 { margin: 0; font-size: 14px; }
.activity-threshold-scope {
  margin: 3px 0 10px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
}
.activity-threshold-group ul { margin: 0; padding: 0; list-style: none; }
.activity-threshold-group li { padding: 8px 0; border-top: 1px solid var(--line); }
.activity-threshold-group li strong,
.activity-threshold-group li span { display: block; }
.activity-threshold-group li strong { font-size: 12px; }
.activity-threshold-group li span { margin-top: 2px; color: var(--ink-soft); font-size: 11px; line-height: 1.5; }
.activity-lenses-grid { margin-top: 0; }
.activity-lens-card { position: relative; }
.activity-lens-card[data-rating="favorable"] { box-shadow: inset 3px 0 0 var(--green); }
.activity-lens-card[data-rating="mixed"] { box-shadow: inset 3px 0 0 var(--gold); }
.activity-lens-card[data-rating="difficult"] { box-shadow: inset 3px 0 0 var(--red); }
.activity-lens-card[data-rating="unavailable"] { box-shadow: inset 3px 0 0 var(--muted); }
.event-list, .analog-list { border-top-color: var(--line-strong); }
table { font-size: 12px; }
th, td { border-color: var(--line); }
.archive-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 4px 0 26px;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
}
.archive-stat {
  min-width: 0;
  padding: 14px 18px;
  border-right: 1px solid var(--line);
}
.archive-stat:first-child { padding-left: 0; border-top: 2px solid var(--blue); }
.archive-stat:nth-child(2) { border-top: 2px solid var(--green); }
.archive-stat:nth-child(3) { border-top: 2px solid var(--gold); }
.archive-stat:nth-child(4) { border-top: 2px solid var(--red); }
.archive-stat:last-child { border-right: 0; }
.archive-stat span,
.archive-stat small {
  display: block;
  color: var(--muted);
  font-size: 11px;
}
.archive-stat strong {
  display: block;
  margin: 2px 0;
  font-size: 22px;
  font-weight: 570;
}
.archive-toolbar {
  display: flex;
  align-items: end;
  gap: 12px;
  padding: 14px 0 22px;
  border-top: 1px solid var(--line);
}
.archive-control { display: grid; gap: 5px; }
.archive-control:first-child { flex: 1 1 340px; }
.archive-control span {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
}
.archive-control input,
.archive-control select {
  min-height: 34px;
  padding: 6px 9px;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  font: inherit;
}
.archive-control input:focus,
.archive-control select:focus {
  border-color: var(--blue);
  outline: 2px solid var(--blue-soft);
  outline-offset: 1px;
}
.archive-visible-count {
  margin-left: auto;
  padding-bottom: 8px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  white-space: nowrap;
}
.archive-group { padding: 24px 0 34px; border-top: 1px solid var(--line); }
.archive-group-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.archive-group-header span { color: var(--muted); font-size: 11px; }
.archive-table { width: 100%; border-collapse: collapse; }
.archive-table th {
  padding: 8px 10px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
  text-align: left;
}
.archive-table td { padding: 12px 10px; vertical-align: middle; }
.archive-table th:first-child,
.archive-table td:first-child { padding-left: 0; }
.archive-date strong,
.archive-date span { display: block; }
.archive-date strong { font-weight: 600; }
.archive-date span { color: var(--muted); font-size: 11px; }
.archive-open { font-weight: 600; text-decoration: none; white-space: nowrap; }
.archive-open:hover { color: var(--blue); text-decoration: underline; }
.archive-empty {
  display: none;
  margin: 12px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.archive-group[data-empty="true"] .archive-empty { display: block; }
.archive-group[data-empty="true"] .table-scroll { display: none; }
.event-kind { display: block; font-weight: 650; }
.event-source { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: 5px; color: var(--muted); font-size: 11px; }
.event-evidence { min-width: 280px; color: var(--ink-soft); line-height: 1.55; }
.event-confidence { font-variant-numeric: tabular-nums; white-space: nowrap; }
.event-download {
  margin: 4px 0 8px;
  color: var(--muted);
  font-size: 11px;
}
.story-section {
  padding: 24px 0 34px;
  border-top: 1px solid var(--line);
}
.story-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
  padding-bottom: 13px;
  border-bottom: 1px solid var(--line-strong);
}
.story-heading h2 { margin: 0; }
.story-legend {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 7px 15px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
}
.story-legend span { display: inline-flex; align-items: center; gap: 6px; }
.story-dot { width: 8px; height: 8px; border-radius: 50%; }
.story-dot.synoptic { background: var(--blue); }
.story-dot.observed { background: var(--gold); }
.story-dot.impact { background: var(--green); }
/* Evidence sits underneath rather than stealing a third of the width from the
   cards, so the graph spans the same 1320px shell every other page uses. */
.story-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
  align-items: stretch;
  padding-top: 10px;
}
.story-field {
  position: relative;
  min-width: 0;
  min-height: 620px;
  overflow: hidden;
  background: var(--paper);
  border: 1px solid var(--line-strong);
  border-radius: 5px;
}
.story-edges,
.story-nodes { position: absolute; inset: 0; width: 100%; height: 100%; }
.story-edges path {
  fill: none;
  stroke: var(--line-strong);
  stroke-width: 1.5;
  marker-end: url(#story-arrow);
}
.story-edges marker path { fill: var(--muted); stroke: none; }
.story-node {
  --node-color: var(--line-strong);
  position: absolute;
  width: 170px;
  min-height: 58px;
  transform: translate(-50%, -50%);
  padding: 9px 10px 10px;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--line-strong);
  border-left: 3px solid var(--node-color);
  border-radius: 5px;
  text-align: left;
  cursor: pointer;
}
.story-node[data-domain="synoptic"] { --node-color: var(--blue); }
.story-node[data-domain="observed"] { --node-color: var(--gold); }
.story-node[data-domain="impact"] { --node-color: var(--green); }
.story-node:hover,
.story-node:focus-visible,
.story-node[aria-pressed="true"] { border-color: var(--node-color); }
.story-node:focus-visible { outline: 2px solid var(--blue-soft); outline-offset: 2px; }
.story-node[aria-pressed="true"] { box-shadow: 0 0 0 2px var(--paper), 0 0 0 4px var(--node-color); }
.story-node-domain,
.story-evidence-domain {
  display: block;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
}
.story-node-label { display: block; padding-top: 2px; font-size: 12px; font-weight: 600; line-height: 1.25; }
/* Full width below the graph, so the reading, the numbers and the connections sit
   side by side instead of stacking into one long narrow column. */
.story-evidence {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr) minmax(0, 1.1fr);
  gap: 0 30px;
  align-items: start;
  min-width: 0;
  padding: 16px 0 4px;
  border-top: 1px solid var(--line-strong);
}
.story-evidence > * { min-width: 0; }
.story-evidence h3 { margin: 5px 0 0; font-size: 17px; }
.story-reading { margin: 11px 0 0; color: var(--ink-soft); font-size: 12px; line-height: 1.6; }
.story-facts { margin: 18px 0 0; }
.story-facts div { padding: 9px 0; border-top: 1px solid var(--line); }
.story-facts dt { color: var(--muted); font-size: 11px; }
.story-facts dd { margin: 2px 0 0; font-size: 12px; font-weight: 600; }
.story-source,
.story-connections { margin-top: 16px; padding-top: 11px; border-top: 1px solid var(--line); }
.story-source { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 11px; }
.story-connections strong { display: block; color: var(--muted); font-size: 11px; }
.story-connections ul { margin: 6px 0 0; padding-left: 17px; color: var(--ink-soft); font-size: 11px; }
.story-evidence-column > :first-child { margin-top: 0; padding-top: 0; border-top: 0; }
.kinematics-motion { margin: 14px 0 4px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.kinematics-motion em {
  display: block;
  margin-top: 2px;
  color: var(--muted);
  font-size: 11px;
  font-style: normal;
}
.kinematics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 8px 26px;
}
.kinematics-table h3 {
  margin: 16px 0 6px;
  font-size: 12px;
}
.kinematics-table h3 span { color: var(--muted); font-weight: 500; }
.kinematics-table td { font-variant-numeric: tabular-nums; }
.attribution { display: block; margin-top: 6px; color: var(--muted); font-size: 11px; line-height: 1.5; }
.attribution a { color: var(--blue); text-decoration: underline; }
.coverage-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 22px; }
.coverage-block h3 { margin: 14px 0 4px; font-size: 12px; }
.coverage-days { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 0; }
.coverage-day {
  flex: 1 1 90px;
  padding: 8px 10px;
  background: var(--rail);
  border: 1px solid var(--line);
  border-left: 3px solid var(--green);
  border-radius: 0 5px 5px 0;
}
.coverage-day[data-thin="true"] { border-left-color: var(--red); background: var(--paper); }
.coverage-day span { display: block; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 11px; }
.coverage-day strong { display: block; margin-top: 2px; font-size: 15px; font-variant-numeric: tabular-nums; }
.coverage-day em { display: block; color: var(--muted); font-size: 11px; font-style: normal; }
.radar-subhead { margin: 18px 0 6px; font-size: 12px; }
.verification-bias { font-variant-numeric: tabular-nums; font-weight: 650; }
.verification-bias[data-sign="high"] { color: var(--red); }
.verification-bias[data-sign="low"] { color: var(--blue); }
.verification-bias[data-sign="level"] { color: var(--muted); }
.verification-notes {
  margin: 11px 0 0;
  padding-left: 17px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
}
.story-caption { margin: 9px 0 0; color: var(--muted); font-size: 11px; }
@media (max-width: 900px) {
  .story-evidence { grid-template-columns: minmax(0, 1fr); gap: 18px 0; }
  .story-evidence-column + .story-evidence-column { padding-top: 14px; border-top: 1px solid var(--line); }
}
.almanac-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: 14px;
  padding: 14px 0 22px;
  border-top: 1px solid var(--line);
}
/* An explicit `display` on a class beats the user-agent [hidden] rule, which silently
   revives anything the scripts try to hide. Keep this ahead of the layout rules. */
[hidden] { display: none !important; }
.almanac-select { display: grid; gap: 5px; }
.almanac-select span {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
  text-transform: none;
}
.almanac-select select {
  min-height: 34px;
  padding: 6px 9px;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  font: inherit;
  min-width: 180px;
}
.almanac-panel { padding: 20px 0 30px; border-top: 1px solid var(--line); }
.almanac-panel-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.almanac-panel-header span { color: var(--muted); font-size: 11px; }
.almanac-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin: 4px 0 22px;
  background: var(--line);
  border: 1px solid var(--line-strong);
}
.almanac-stats div { padding: 12px 14px; background: var(--paper); }
.almanac-stats span {
  display: block;
  color: var(--muted);
  font-size: 11px;
}
.almanac-stats strong { display: block; margin-top: 2px; font-size: 18px; font-weight: 600; }
.almanac-records { margin: 8px 0 0; padding: 0; list-style: none; }
.almanac-records li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-top: 1px solid var(--line);
  font-size: 12px;
}
.almanac-records li span { color: var(--muted); }
.record-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 1px;
  margin: 4px 0;
  background: var(--line);
  border: 1px solid var(--line-strong);
}
.record-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px 16px 14px;
  background: var(--paper);
  border-top: 2px solid var(--blue);
}
.record-label {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
}
.record-value { font-size: 22px; font-weight: 650; }
.record-date { color: var(--muted); font-size: 11px; }
.muted-cell { color: var(--muted); }
footer {
  margin: 0;
  color: var(--muted);
  background: var(--paper);
  border-top: 1px solid var(--line);
}
.footer-wrap {
  width: min(100%, 1320px);
  margin: 0 auto;
  padding: 18px 48px;
  font-size: 11px;
}
@media (max-width: 1180px) {
  .page-layout { grid-template-columns: minmax(0, 1fr); }
  .page-outline { display: none; }
}
@media (max-width: 980px) and (min-width: 721px) {
  :root { --sidebar: 190px; }
  .page-shell { padding-right: 32px; padding-left: 32px; }
  .nav-wrap { padding: 8px; flex-wrap: nowrap; }
  .primary-nav { width: auto; flex: 0 0 auto; flex-wrap: nowrap; }
  .primary-nav a { min-height: 30px; }
  .story-layout { grid-template-columns: 1fr; }
  .story-evidence { padding: 17px 0 0; border-top: 1px solid var(--line-strong); border-left: 0; }
}
@media (max-width: 720px) {
  .app-shell { display: block; }
  .site-header {
    position: fixed;
    left: 0;
    width: min(86vw, 290px);
    height: 100vh;
    transform: translateX(-105%);
    border-right: 1px solid var(--line-strong);
    box-shadow: 12px 0 30px rgba(0,0,0,.12);
    transition: transform 180ms ease;
  }
  .site-header.open { transform: translateX(0); }
  .nav-wrap { padding: 8px; flex-wrap: nowrap; gap: 0; }
  .primary-nav { order: initial; width: auto; flex: 0 0 auto; overflow: visible; }
  .primary-nav a { min-height: 30px; }
  .report-topbar { padding: 0 14px; }
  .menu-button { display: grid; }
  .breadcrumbs .optional { display: none; }
  .sidebar-scrim {
    position: fixed;
    inset: 0;
    z-index: 28;
    background: rgba(30,30,28,.25);
  }
  .sidebar-scrim.open { display: block; }
  .page-shell { padding: 28px 20px 56px; }
  .activity-lenses-section { padding: 18px 14px 20px; }
  .activity-method-steps,
  .activity-threshold-groups { grid-template-columns: 1fr; }
  .activity-method-step,
  .activity-method-step:nth-child(2n),
  .activity-method-step:nth-last-child(-n+2) { border-right: 0; border-bottom: 1px solid var(--line); }
  .activity-method-step:last-child { border-bottom: 0; }
  .publication-state { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .publication-state > div,
  .publication-state > div:first-child,
  .publication-state > div:last-child { padding: 10px 9px; border-bottom: 1px solid var(--line); }
  .publication-state > div:nth-child(2n) { border-right: 0; }
  .publication-state > div:nth-last-child(-n+2) { border-bottom: 0; }
  h1, .page-intro h1 { font-size: 28px; }
  .home-intro { padding-top: 6px; }
  .home-intro h1 { font-size: 32px; }
  .home-question { font-size: 20px; }
  .publication-row { grid-template-columns: 1fr; gap: 6px; padding: 16px 0; }
  .publication-date { text-align: left; }
  .home-definition { grid-template-columns: 1fr; }
  .home-definition div,
  .home-definition div:first-child {
    padding: 12px 0;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .home-definition div:last-child { border-bottom: 0; }
  .hero { padding-top: 0; }
  .summary, .public-facts, .metric-band, .diagnostic-ledger,
  .methods-grid, .download-list, .insight-grid, .archive-summary { grid-template-columns: 1fr; }
  .score, .score:first-child, .score:nth-child(2), .score:nth-child(3),
  .metric, .public-facts div, .public-facts div:first-child,
  .public-facts div:nth-child(2), .public-facts div:nth-child(3) {
    padding: 13px 0;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .score:last-child, .metric:last-child, .public-facts div:last-child { border-bottom: 0; }
  .archive-stat,
  .archive-stat:first-child,
  .archive-stat:nth-child(2),
  .archive-stat:nth-child(3),
  .archive-stat:nth-child(4) {
    padding: 12px 0;
    border-top: 0;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .archive-stat:last-child { border-bottom: 0; }
  .archive-toolbar { align-items: stretch; flex-direction: column; }
  .archive-control:first-child { flex-basis: auto; }
  .archive-visible-count { margin-left: 0; padding-bottom: 0; }
  .archive-table th:nth-child(3),
  .archive-table td:nth-child(3) { display: none; }
  .source-note { margin-left: 0; }
  .story-heading { align-items: flex-start; flex-direction: column; }
  .story-legend { justify-content: flex-start; }
  .story-layout { grid-template-columns: 1fr; }
  .story-field { min-height: 780px; }
  .story-node { width: min(180px, 44%); }
  .story-evidence { padding: 17px 0 0; border-top: 1px solid var(--line-strong); border-left: 0; }
  .viz-frame { min-width: 720px; }
  .footer-wrap { padding: 18px 20px; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
"""


def _front_phrase(fronts: FrontAnalysis) -> str:
    """Render a frontal count, or say the series was not there to search."""
    if bool(getattr(fronts, "available", True)):
        return f"{len(fronts.events)} objective frontal passage candidate(s)"
    return "no frontal analysis (the surface series was unavailable, so none was attempted)"


def _phenomena_phrase(phenomena: PhenomenaAnalysis) -> str:
    """Render a phenomena count, naming any input the detector had to do without.

    The ledger reads station, radar and lightning. An empty result with one of
    them missing means the evidence was absent, not that the period was quiet.
    """
    count = len(phenomena.events)
    degraded = list(getattr(phenomena, "degraded_inputs", []) or [])
    if not degraded:
        return f"{count} objective phenomenon candidate(s)"
    missing = ", ".join(degraded)
    return (
        f"{count} objective phenomenon candidate(s), detected without {missing}, "
        "so an empty ledger reflects missing evidence rather than a quiet period"
    )


def _radar_peak_phrase(radar: RadarArchive, peak: float) -> str:
    """Render the radar peak, or say the archive did not answer."""
    if not bool(getattr(radar, "available", True)):
        return "an unavailable radar archive (no reflectivity reading, not an absence of echo)"
    return f"a maximum sampled radar reflectivity of {_fmt(peak)} dBZ"


def _lightning_phrase(lightning: LightningArchive, count: int) -> str:
    """Render a strike count, or say the archive was unavailable.

    A failed archive and a genuinely quiet period both leave an empty frame, and
    the quiet reading is the comforting one, so it must never be printed by
    default.
    """
    if bool(getattr(lightning, "available", True)):
        return f"{count:,} lightning event(s)"
    return "an unavailable lightning archive (no strike count, not zero strikes)"


def _fmt(value: float, digits: int = 1) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _fmt_grouped(value: float, digits: int = 0) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:,.{digits}f}"


def _load_activity_lenses(
    source: Path | None,
    expected_date: str,
    expected_timezone: str,
) -> dict[str, Any] | None:
    """Load the exact saved lens evidence that the daily page will render."""

    if source is None:
        return None
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Activity-lens evidence is unreadable: {source}") from exc
    if not isinstance(document, dict):
        raise ValueError("Activity-lens evidence must be a JSON object")
    if document.get("schema") != ACTIVITY_LENS_SCHEMA:
        raise ValueError("Activity-lens evidence uses an unsupported schema")
    if document.get("date") != expected_date:
        raise ValueError("Activity-lens evidence does not match the daily edition date")
    if document.get("timezone") != expected_timezone:
        raise ValueError("Activity-lens evidence does not match the configured timezone")
    lenses = document.get("lenses")
    if not isinstance(lenses, list):
        raise ValueError("Activity-lens evidence has no lens list")
    lens_ids = [lens.get("id") for lens in lenses if isinstance(lens, dict)]
    if len(lens_ids) != len(lenses) or set(lens_ids) != set(available_lens_ids()):
        raise ValueError("Activity-lens evidence has an incomplete or unknown lens set")
    if len(lens_ids) != len(set(lens_ids)):
        raise ValueError("Activity-lens evidence contains duplicate lenses")
    methodology = document.get("methodology")
    if not isinstance(methodology, dict):
        raise ValueError("Activity-lens evidence has no calculation methodology")
    method_lenses = methodology.get("lenses")
    if not isinstance(method_lenses, list):
        raise ValueError("Activity-lens methodology has no lens rules")
    method_ids = [lens.get("id") for lens in method_lenses if isinstance(lens, dict)]
    if len(method_ids) != len(method_lenses) or set(method_ids) != set(available_lens_ids()):
        raise ValueError("Activity-lens methodology has an incomplete or unknown lens set")
    return document


_ACTIVITY_FACT_LABELS = {
    "precipitation_total_mm": "Precipitation total",
    "wet_hours": "Hours with precipitation",
    "wind_gust_max_ms": "Peak wind gust",
    "temperature_min_c": "Minimum temperature",
    "temperature_max_c": "Maximum temperature",
    "solar_index": "Normalized solar index",
    "hot_humid_hours": "Warm and humid hours",
    "cold_hours": "Hours below 5 C",
}


def _activity_lens_methodology(document: dict[str, Any]) -> str:
    methodology = document["methodology"]
    base_score = html.escape(str(methodology.get("base_score", 100)))
    coverage = float(methodology.get("minimum_required_fact_coverage", 0.9)) * 100.0
    groups: list[str] = []
    for lens in methodology["lenses"]:
        label = html.escape(str(lens.get("label", lens.get("id", "Activity"))))
        scope = (
            "06:00-10:00 and 15:00-19:00"
            if lens.get("scope") == "commute-hours"
            else "Full local day"
        )
        rule_items: list[str] = []
        for rule in lens.get("rules", []):
            fact = str(rule.get("fact", "Evidence"))
            fact_label = html.escape(
                _ACTIVITY_FACT_LABELS.get(fact, fact.replace("_", " ").title())
            )
            thresholds = "; ".join(
                f'{html.escape(str(band.get("condition", "")))}: '
                f'&minus;{html.escape(str(band.get("deduction", "")))}'
                for band in rule.get("bands", [])
                if isinstance(band, dict)
            )
            rule_items.append(
                f"<li><strong>{fact_label}</strong><span>{thresholds}</span></li>"
            )
        groups.append(
            '<section class="activity-threshold-group">'
            f"<h3>{label}</h3>"
            f'<p class="activity-threshold-scope">{html.escape(scope)}</p>'
            f"<ul>{''.join(rule_items)}</ul></section>"
        )
    calculation = html.escape(str(methodology.get("calculation", "")))
    coverage_policy = html.escape(str(methodology.get("coverage_policy", "")))
    return f"""
  <ol class="activity-method-steps" aria-label="How activity lens scores are calculated">
    <li class="activity-method-step"><span>1</span><div><strong>Begin at {base_score}</strong><p>Every activity lens starts with {base_score} points.</p></div></li>
    <li class="activity-method-step"><span>2</span><div><strong>Subtract crossed thresholds</strong><p>Each weather rule can apply one stated penalty. All matching rule penalties are added together.</p></div></li>
    <li class="activity-method-step"><span>3</span><div><strong>Translate the final score</strong><p>80-100 is favorable, 55-79 is mixed, and 0-54 is difficult.</p></div></li>
    <li class="activity-method-step"><span>4</span><div><strong>Require complete evidence</strong><p>A lens is withheld below {coverage:g}% coverage for any required fact; the other lenses remain available.</p></div></li>
  </ol>
  <details class="activity-lens-method">
    <summary>See the exact penalty thresholds for all six lenses</summary>
    <p>{calculation} {coverage_policy}</p>
    <div class="activity-threshold-groups">{''.join(groups)}</div>
  </details>
"""


def _activity_lenses_section(
    document: dict[str, Any] | None,
    data_href: str | None,
) -> str:
    """Render saved lens evidence with Atlas's existing content components."""

    if document is None:
        return ""
    cards: list[str] = []
    for lens in document["lenses"]:
        label = html.escape(str(lens.get("label", lens.get("id", "Activity"))))
        status = lens.get("status")
        if status == "available":
            rating_key = str(lens.get("rating", "unrated")).casefold()
            rating = rating_key.replace("-", " ").title()
            score = lens.get("score")
            provenance = f"{rating} &middot; {html.escape(str(score))}/100"
            detail = html.escape(str(lens.get("summary", "")))
            factors = lens.get("limiting_factors", [])
            if isinstance(factors, list) and factors:
                explanations = []
                for factor in factors:
                    if not isinstance(factor, dict):
                        continue
                    explanation = html.escape(str(factor.get("explanation", "Limiting condition.")))
                    value = html.escape(str(factor.get("value", "n/a")))
                    unit = html.escape(str(factor.get("unit", "")))
                    deduction = html.escape(str(factor.get("deduction", "n/a")))
                    explanations.append(
                        f"{explanation} ({value} {unit}; &minus;{deduction} points.)"
                    )
                if explanations:
                    detail = f"{detail} {' '.join(explanations)}"
        else:
            rating_key = "unavailable"
            provenance = "Insufficient evidence"
            missing = lens.get("missing_or_sparse_facts", [])
            missing_labels = ", ".join(
                html.escape(str(item).replace("_", " "))
                for item in missing
            )
            detail = "This lens was withheld because its required daily evidence was incomplete."
            if missing_labels:
                detail += f" Missing or sparse: {missing_labels}."
        cards.append(
            f'<article class="insight activity-lens-card" data-rating="{html.escape(rating_key)}">'
            f'<span class="provenance">{provenance}</span>'
            f"<h3>{label}</h3><p>{detail}</p></article>"
        )
    evidence_link = (
        f' <a href="{html.escape(data_href)}" download>Download the full evidence JSON</a>.'
        if data_href
        else ""
    )
    return f"""
<section class="content-section activity-lenses-section" aria-labelledby="activity-lenses-heading">
  <div class="section-heading"><span class="activity-lenses-symbol" aria-hidden="true"></span><h2 id="activity-lenses-heading">Activity Lenses</h2></div>
  <p class="public-lead">How the completed day suited six everyday activities, using fixed and inspectable convenience thresholds. Scores of 80 or more are favorable, 55-79 are mixed, and lower scores are difficult.</p>
  <div class="insight-grid activity-lenses-grid" aria-label="Daily activity lens ratings">{''.join(cards)}</div>
{_activity_lens_methodology(document)}
  <p class="evidence-meta">{html.escape(str(document.get("disclaimer", "")))}{evidence_link}</p>
</section>
"""


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
    accessory_names = {"satellite_media"}
    for parent in {source.parent for source in figure_paths.values()}:
        for accessory_name in accessory_names:
            accessory = parent / accessory_name
            if not accessory.is_dir():
                continue
            target = assets_dir / accessory_name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(accessory, target)
    return relative


def _site_origin(config: AtlasConfig) -> str:
    return config.project.site_url.rstrip("/")


SHARE_CARD_ASSET = "share-card.png"
ANALYSIS_SHARE_CARD_ASSET = "share-card-analysis.png"


def _share_card_asset(family: str) -> str:
    """The daily report and the 72-hour analysis describe different periods, so each
    gets its own preview image rather than sharing one misleading card."""
    return ANALYSIS_SHARE_CARD_ASSET if family == "analysis" else SHARE_CARD_ASSET

# Ordered by preference, then by how likely the file is to exist on the build machine:
# Windows first for local runs, DejaVu for the Ubuntu CI runner, macOS last.
_FONT_CANDIDATES = {
    "bold": (
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ),
    "regular": (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ),
    # The site sets eyebrows and small labels in a monospace face.
    "mono": (
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
    ),
}


def _load_font(size: int, weight: str = "regular") -> ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES[weight]:
        path = Path(candidate)
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    try:
        # Pillow 10.1+ scales its built-in font; older builds only offer a fixed size.
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) > max_width and current:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                return lines
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _share_number(value: Any, digits: int, suffix: str) -> str:
    if value is None:
        return "\u2014"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "\u2014"
    if pd.isna(number):
        return "\u2014"
    return f"{number:.{digits}f}{suffix}"


def write_share_card(
    config: AtlasConfig,
    share: dict[str, Any] | None,
    site_dir: Path,
    asset_name: str = SHARE_CARD_ASSET,
) -> Path | None:
    """Render the 1200x630 link-preview image referenced by the Open Graph tags.

    The in-page share button draws its own portrait card in canvas; this is the
    landscape one Facebook, X and WhatsApp fetch when somebody posts a link.
    """
    if not share:
        return None
    width, height = 1200, 630
    pad = 84
    # Same treatment as the in-page card: paper, ink, hairline rules and one muted
    # blue accent, so a shared link previews as the site rather than against it.
    ink = "#232323"
    ink_soft = "#50504d"
    muted = "#7b7a77"
    line = "#e7e7e3"
    blue = "#3f72a4"

    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle([18, 18, width - 19, height - 19], outline=line, width=2)
    draw.rectangle([pad, 92, pad + 84, 97], fill=blue)

    location = str(share.get("location") or f"{config.location.name}, {config.location.region}")
    eyebrow = location
    if share.get("kind_label"):
        eyebrow = f"{location} · {share['kind_label']}"
    draw.text((pad, 128), eyebrow.upper(), font=_load_font(22, "mono"), fill=muted)

    draw.text(
        (pad, 178),
        _share_number(share.get("temperature_c"), 0, "\u00b0"),
        font=_load_font(140, "bold"),
        fill=ink,
    )

    label_font = _load_font(42, "bold")
    label_lines = _wrap_lines(draw, share.get("regime_label") or "Weather summary", label_font, width - pad * 2, 1)
    draw.text((pad, 356), label_lines[0] if label_lines else "", font=label_font, fill=ink)

    body_font = _load_font(25)
    body_y = 424
    for body_line in _wrap_lines(draw, share.get("regime_briefing") or "", body_font, width - pad * 2, 2):
        draw.text((pad, body_y), body_line, font=body_font, fill=ink_soft)
        body_y += 34

    draw.line([(pad, height - 138), (width - pad, height - 138)], fill=line, width=2)

    stats = [
        ("PRECIP", _share_number(share.get("precipitation_mm"), 1, " mm")),
        ("WIND", _share_number(share.get("wind_ms"), 1, " m/s")),
        ("CLOUD", _share_number(share.get("cloud_pct"), 0, "%")),
    ]
    label_font = _load_font(20, "mono")
    value_font = _load_font(28, "bold")
    column = pad
    for stat_label, stat_value in stats:
        draw.text((column, height - 112), stat_label, font=label_font, fill=muted)
        draw.text((column, height - 84), stat_value, font=value_font, fill=ink)
        column += 240

    draw.text(
        (pad, height - 44),
        f"{config.project.name} · {share.get('date') or ''}".upper(),
        font=_load_font(19, "mono"),
        fill=muted,
    )

    assets_dir = site_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    target = assets_dir / asset_name
    image.save(target, format="PNG", optimize=True)
    return target


def _social_meta(
    config: AtlasConfig,
    active: str,
    family: str,
    title: str,
    description: str,
) -> str:
    """Open Graph and Twitter card tags.

    Facebook, X and WhatsApp shares carry the page URL, so without these a shared link
    renders as a bare string. The preview image is the build-time card in assets/.
    """
    origin = _site_origin(config)
    folder = {"analysis": "analysis/", "archive": "archive/"}.get(family, "")
    page_url = f"{origin}/{folder}{active}"
    image_url = f"{origin}/assets/{_share_card_asset(family)}"
    tags = [
        f'<link rel="canonical" href="{html.escape(page_url)}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{html.escape(config.project.name)}">',
        f'<meta property="og:title" content="{html.escape(title)}">',
        f'<meta property="og:description" content="{html.escape(description)}">',
        f'<meta property="og:url" content="{html.escape(page_url)}">',
        f'<meta property="og:image" content="{html.escape(image_url)}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{html.escape(title)}">',
        f'<meta name="twitter:description" content="{html.escape(description)}">',
        f'<meta name="twitter:image" content="{html.escape(image_url)}">',
    ]
    return "".join(f"  {tag}\n" for tag in tags)


def _report_url(config: AtlasConfig) -> str:
    """Canonical address of the daily public report.

    Link shares carry a URL rather than the card image, so every page that embeds the
    share payload points at the report the card describes.
    """
    return f"{_site_origin(config)}/report.html"


def _analysis_url(config: AtlasConfig) -> str:
    """Canonical address of the 72-hour meteorological analysis."""
    return f"{_site_origin(config)}/analysis/index.html"


def _navigation(active: str, family: str, share_id: str | None = None) -> str:
    nested = family == "analysis"
    archive = family == "archive"
    archive_family = family in ("archive", "summary", "records")
    prefix = "../" if nested or archive else ""
    links: list[str] = []
    if family in ("public", "analysis"):
        pages = ANALYSIS_PAGES if nested else PUBLIC_PAGES
        for filename, label in pages:
            current = ' aria-current="page"' if filename == active else ""
            links.append(f'<a href="{filename}"{current}>{html.escape(label)}</a>')
    elif archive_family:
        archive_pages = (
            (f"{prefix}summary.html", "Season & month summary", family == "summary"),
            (f"{prefix}records.html", "Record Book", family == "records"),
            (
                "index.html#weather-event-index"
                if archive
                else f"{prefix}archive/index.html#weather-event-index",
                "Weather Event Index",
                False,
            ),
        )
        for href, label, current_page in archive_pages:
            current = ' aria-current="page"' if current_page else ""
            links.append(f'<a href="{href}"{current}>{html.escape(label)}</a>')
    public_current = ' aria-current="true"' if family == "public" else ""
    analysis_current = ' aria-current="true"' if family == "analysis" else ""
    archive_current = ' aria-current="true"' if archive_family else ""
    family_label = {
        "public": "Daily public report",
        "analysis": "72-hour analysis",
        "archive": "Archive",
        "summary": "Archive",
        "records": "Archive",
        "home": "Atlas project",
    }[family]
    page_navigation = (
        f'<span class="nav-label">{family_label}</span>'
        f'<nav class="primary-nav" aria-label="Primary">{"".join(links)}</nav>'
        if links
        else ""
    )
    archive_href = "index.html" if archive else f"{prefix}archive/index.html"
    # The report always describes the last complete day, never "today" — the label says so
    # rather than promising same-day data the archive cannot deliver.
    share_button = (
        f'<div class="share-wrap" data-atlas-share-root>'
        f'<button type="button" class="share-day-button" data-atlas-share-button'
        f' data-atlas-share-target="{html.escape(share_id)}"'
        f' aria-haspopup="true" aria-expanded="false" disabled>'
        f'<span aria-hidden="true">&#x2934;</span> Share this report</button>'
        f'<div class="share-menu" data-atlas-share-menu hidden>'
        f'<p class="share-menu-title">Report card for <strong data-atlas-share-date></strong></p>'
        f'<button type="button" class="share-menu-primary" data-atlas-share-action="download">'
        f'Download image <span>1080&times;1350 PNG</span></button>'
        f'<button type="button" class="share-menu-item" data-atlas-share-action="native" hidden>'
        f'Share to an app&hellip;</button>'
        f'<p class="share-menu-label">Share to</p>'
        f'<div class="share-menu-links">'
        f'<button type="button" class="share-menu-item" data-atlas-share-action="facebook">Facebook</button>'
        f'<button type="button" class="share-menu-item" data-atlas-share-action="x">X</button>'
        f'<button type="button" class="share-menu-item" data-atlas-share-action="instagram">Instagram</button>'
        f'</div>'
        f'<button type="button" class="share-menu-item" data-atlas-share-action="copy">Copy link</button>'
        f'</div></div>'
        if share_id
        else ""
    )
    return (
        f'<div class="nav-wrap"><a class="brand" href="{prefix}index.html">Atlas</a>'
        f'<span class="nav-label">Publications</span>'
        f'<nav class="report-switch" aria-label="Atlas publications"><a href="{prefix}report.html"{public_current}>Daily Report</a>'
        f'<a href="{prefix}analysis/index.html"{analysis_current}>72-Hour Analysis</a>'
        f'<a href="{archive_href}"{archive_current}>Archive</a></nav>'
        f'{page_navigation}'
        f'{share_button}'
        f'<div class="sidebar-note"><strong>Debrecen, Hungary</strong>'
        f'Daily public record and rolling expert analysis.</div></div>'
    )


def _heading_slug(value: str) -> str:
    plain = html.unescape(re.sub(r"<[^>]+>", "", value)).casefold()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "section"


def _analysis_outline(content: str) -> tuple[str, str]:
    """Add stable heading anchors and a compact outline to long analysis pages."""
    headings: list[tuple[str, str]] = []
    used: set[str] = set()
    pattern = re.compile(r"<h2(?P<attrs>[^>]*)>(?P<label>.*?)</h2>", re.IGNORECASE | re.DOTALL)

    def anchor(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        label_html = match.group("label")
        label = html.unescape(re.sub(r"<[^>]+>", "", label_html)).strip()
        existing = re.search(r'\bid=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        slug = existing.group(1) if existing else _heading_slug(label)
        base = slug
        suffix = 2
        while slug in used:
            slug = f"{base}-{suffix}"
            suffix += 1
        used.add(slug)
        headings.append((slug, label))
        if not existing:
            attrs = f'{attrs} id="{html.escape(slug)}"'
        return f"<h2{attrs}>{label_html}</h2>"

    anchored = pattern.sub(anchor, content)
    if len(headings) < 2:
        return anchored, ""
    links = "".join(
        f'<a href="#{html.escape(slug)}">{html.escape(label)}</a>'
        for slug, label in headings
    )
    outline = (
        '<aside class="page-outline" aria-label="On this page">'
        '<nav><strong>On this page</strong>'
        f'{links}</nav></aside>'
    )
    return anchored, outline


def _publication_strip(
    family: str,
    period: str,
    updated: str,
    complete: bool,
) -> str:
    label = {
        "public": "Daily observation",
        "analysis": "72-hour reconstruction",
        "weekly": "Preserved observation",
    }.get(family, "Observed record")
    state = "Complete" if complete else "Incomplete"
    state_note = (
        "Required observation coverage passed"
        if complete
        else "Required evidence is incomplete; see Methods"
    )
    return f"""
<section class="publication-state" aria-label="Publication state" data-state="{state.casefold()}">
  <div><span>Record type</span><strong>{label}</strong><small>Observed, not forecast</small></div>
  <div><span>Observed period</span><strong>{html.escape(period)}</strong></div>
  <div class="publication-integrity"><span>Integrity</span><strong>{state}</strong><small>{state_note}</small></div>
  <div><span>Updated</span><strong>{html.escape(updated)}</strong></div>
</section>
"""


def _evidence_badge(kind: str, label: str | None = None) -> str:
    normalized = kind.casefold().replace("_", "-").replace(" ", "-")
    aliases = {
        "observed": "observed",
        "remote": "remote",
        "remote-sensed": "remote",
        "gridded": "model",
        "model": "model",
        "model-derived": "model",
        "derived": "derived",
        "other": "derived",
    }
    css_class = aliases.get(normalized, "derived")
    default = {
        "observed": "Observed",
        "remote": "Remote-sensed",
        "model": "Model-derived",
        "derived": "Derived",
    }[css_class]
    return f'<span class="evidence-badge {css_class}">{html.escape(label or default)}</span>'


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
    <iframe class="{classes}" src="{html.escape(path)}" title="{html.escape(frame_title)}" loading="lazy" fetchpriority="low" scrolling="no" data-atlas-figure></iframe>
  </div>
  <p class="figure-open"><a href="{html.escape(path)}" target="_blank" rel="noopener">Open this interactive figure in a separate page</a>.</p>
</section>
"""


SHARE_SCRIPT = r"""<script>
  (function () {
    const root = document.querySelector('[data-atlas-share-root]');
    const shareButton = document.querySelector('[data-atlas-share-button]');
    const menu = document.querySelector('[data-atlas-share-menu]');
    if (!root || !shareButton || !menu) return;
    const dataId = shareButton.getAttribute('data-atlas-share-target');
    const dataEl = dataId ? document.getElementById(dataId) : null;
    if (!dataEl) return;

    let share = null;
    try {
      share = JSON.parse(dataEl.textContent);
    } catch (err) {
      return;
    }
    shareButton.disabled = false;

    // The canonical link is per page, so sharing from Storms links to Storms rather
    // than to whichever page the card's period happens to headline.
    const canonical = document.querySelector('link[rel="canonical"]');
    const pageUrl = (canonical && canonical.href) || share.page_url || window.location.href;
    const dateEl = menu.querySelector('[data-atlas-share-date]');
    if (dateEl) dateEl.textContent = share.date || 'the latest edition';

    const numberOrDash = (value, digits, suffix) =>
      value === null || value === undefined || Number.isNaN(value)
        ? '—'
        : `${Number(value).toFixed(digits)}${suffix}`;

    const wrapText = (ctx, text, x, y, maxWidth, lineHeight, maxLines) => {
      const words = String(text || '').split(' ');
      let line = '';
      let cursorY = y;
      let lines = 0;
      for (const word of words) {
        const test = line ? `${line} ${word}` : word;
        if (ctx.measureText(test).width > maxWidth && line) {
          ctx.fillText(line, x, cursorY);
          line = word;
          cursorY += lineHeight;
          lines += 1;
          if (lines >= maxLines) return cursorY;
        } else {
          line = test;
        }
      }
      if (line) ctx.fillText(line, x, cursorY);
      return cursorY;
    };

    // 1080x1350 is Instagram's tallest feed frame and crops cleanly on Facebook.
    // Styled as the site is: paper, ink, hairline rules and one muted blue accent,
    // rather than the saturated gradient it used to carry.
    const INK = '#232323';
    const INK_SOFT = '#50504d';
    const MUTED = '#7b7a77';
    const LINE = '#e7e7e3';
    const BLUE = '#3f72a4';
    const MONO = 'ui-monospace, SFMono-Regular, Consolas, monospace';
    const SANS = 'Inter, Segoe UI, Arial, sans-serif';

    const buildCard = () => {
      const W = 1080;
      const H = 1350;
      const PAD = 96;
      const canvas = document.createElement('canvas');
      canvas.width = W;
      canvas.height = H;
      const ctx = canvas.getContext('2d');

      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = LINE;
      ctx.lineWidth = 2;
      ctx.strokeRect(30, 30, W - 60, H - 60);

      // The blue rule echoes the accent on the site's navigation cards.
      ctx.fillStyle = BLUE;
      ctx.fillRect(PAD, 150, 96, 6);

      const location = String(share.location || 'Debrecen, Hungary');
      const eyebrow = share.kind_label ? `${location} · ${share.kind_label}` : location;
      ctx.fillStyle = MUTED;
      ctx.font = `600 26px ${MONO}`;
      ctx.fillText(eyebrow.toUpperCase(), PAD, 224);

      ctx.fillStyle = INK;
      ctx.font = `800 240px ${SANS}`;
      ctx.fillText(numberOrDash(share.temperature_c, 0, '°'), PAD, 476);

      ctx.font = `700 58px ${SANS}`;
      wrapText(ctx, share.regime_label || 'Weather summary', PAD, 574, W - PAD * 2, 70, 2);

      ctx.fillStyle = INK_SOFT;
      ctx.font = `400 32px ${SANS}`;
      wrapText(ctx, share.regime_briefing || '', PAD, 690, W - PAD * 2, 46, 4);

      const rows = [
        ['Precipitation', numberOrDash(share.precipitation_mm, 1, ' mm')],
        ['Wind', numberOrDash(share.wind_ms, 1, ' m/s')],
        ['Cloud cover', numberOrDash(share.cloud_pct, 0, '%')],
      ];
      if (share.energy_label) rows.push(['Energy', String(share.energy_label)]);

      let rowY = 902;
      for (const [label, value] of rows) {
        ctx.strokeStyle = LINE;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(PAD, rowY - 34);
        ctx.lineTo(W - PAD, rowY - 34);
        ctx.stroke();

        ctx.fillStyle = MUTED;
        ctx.font = `500 24px ${MONO}`;
        ctx.textAlign = 'left';
        ctx.fillText(label.toUpperCase(), PAD, rowY);
        ctx.fillStyle = INK;
        ctx.font = `700 34px ${SANS}`;
        ctx.textAlign = 'right';
        ctx.fillText(value, W - PAD, rowY);
        ctx.textAlign = 'left';
        rowY += 78;
      }

      ctx.strokeStyle = LINE;
      ctx.beginPath();
      ctx.moveTo(PAD, H - 168);
      ctx.lineTo(W - PAD, H - 168);
      ctx.stroke();

      ctx.fillStyle = MUTED;
      ctx.font = `500 24px ${MONO}`;
      ctx.fillText(`ATLAS · ${String(share.date || '').toUpperCase()}`, PAD, H - 122);
      ctx.fillText(String(pageUrl).replace(/^https?:\/\//, ''), PAD, H - 82);

      return canvas;
    };

    // Period cards carry a date range, so the raw value is not filename-safe.
    const slug = value => String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const fileName = `debrecen-${slug(share.kind_label || 'report')}-${slug(share.date || 'latest')}.png`;
    const shareText = `${share.regime_label || 'Debrecen weather'} — ${numberOrDash(share.temperature_c, 0, '°C')} in ${share.location || 'Debrecen'} on ${share.date || ''}`;

    const toBlob = () =>
      new Promise(resolve => buildCard().toBlob(blob => resolve(blob), 'image/png'));

    const setMenu = open => {
      menu.hidden = !open;
      shareButton.setAttribute('aria-expanded', String(open));
    };

    const download = async () => {
      const blob = await toBlob();
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    };

    const openIntent = url => window.open(url, '_blank', 'noopener,noreferrer');

    // navigator.clipboard is undefined outside a secure context, so the archived
    // copies opened from disk need the selection fallback to copy at all.
    const copyText = async text => {
      if (navigator.clipboard && window.isSecureContext) {
        try {
          await navigator.clipboard.writeText(text);
          return true;
        } catch (err) {
          /* fall through to the selection fallback */
        }
      }
      const field = document.createElement('textarea');
      field.value = text;
      field.setAttribute('readonly', '');
      field.style.position = 'fixed';
      field.style.top = '-1000px';
      document.body.appendChild(field);
      field.select();
      field.setSelectionRange(0, text.length);
      let copied = false;
      try {
        copied = document.execCommand('copy');
      } catch (err) {
        copied = false;
      }
      field.remove();
      return copied;
    };

    const actions = {
      download,
      // Offered only where the browser can hand over the actual PNG, which is the one
      // route to Instagram. Desktop never sees it, so the OS mail sheet never opens.
      native: async () => {
        const blob = await toBlob();
        if (!blob) return;
        const file = new File([blob], fileName, { type: 'image/png' });
        try {
          await navigator.share({ files: [file], text: shareText });
        } catch (err) {
          /* cancelled by the reader */
        }
      },
      facebook: () =>
        openIntent(`https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(pageUrl)}`),
      x: () =>
        openIntent(
          `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(pageUrl)}`,
        ),
      // Instagram accepts no prefilled web post, so the only honest route is to put
      // the image on the device first. On a phone the share sheet lists Instagram
      // directly; elsewhere the card downloads and Instagram opens for the upload.
      instagram: async () => {
        if (nativeFilesSupported) {
          await actions.native();
          return;
        }
        // Opened before the await, while the click still counts as user activation;
        // afterwards a popup blocker would swallow it.
        openIntent('https://www.instagram.com/');
        await download();
      },
      copy: async event => {
        const button = event.currentTarget;
        const original = button.dataset.label || button.textContent;
        button.dataset.label = original;
        if (await copyText(pageUrl)) {
          button.textContent = 'Link copied';
          window.setTimeout(() => {
            button.textContent = original;
          }, 1800);
          return;
        }
        // Both clipboard routes can be refused. Leave the link on screen and selected
        // so it stays copyable by hand instead of failing silently.
        button.textContent = 'Copy this link';
        let fallback = menu.querySelector('[data-atlas-share-url]');
        if (!fallback) {
          fallback = document.createElement('input');
          fallback.type = 'text';
          fallback.readOnly = true;
          fallback.className = 'share-menu-url';
          fallback.setAttribute('data-atlas-share-url', '');
          fallback.value = pageUrl;
          menu.append(fallback);
        }
        fallback.focus();
        fallback.select();
      },
    };

    let nativeFilesSupported = false;
    try {
      const probe = new File([new Blob(['x'])], 'probe.png', { type: 'image/png' });
      nativeFilesSupported = Boolean(navigator.canShare && navigator.canShare({ files: [probe] }));
    } catch (err) {
      nativeFilesSupported = false;
    }
    const nativeButton = menu.querySelector('[data-atlas-share-action="native"]');
    if (nativeButton && nativeFilesSupported) nativeButton.hidden = false;

    shareButton.addEventListener('click', () => setMenu(menu.hidden));
    menu.querySelectorAll('[data-atlas-share-action]').forEach(button => {
      button.addEventListener('click', event => {
        const name = button.getAttribute('data-atlas-share-action');
        const action = actions[name];
        if (action) action(event);
        if (name !== 'copy') setMenu(false);
      });
    });
    document.addEventListener('click', event => {
      if (!root.contains(event.target)) setMenu(false);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') setMenu(false);
    });
  })();
</script>"""


FIGURE_RESIZE_SCRIPT = r"""<script data-atlas-figure-resize>
  (() => {
    const fitFigure = frame => {
      try {
        const figureDocument = frame.contentDocument;
        if (!figureDocument?.body) return;
        const resize = () => {
          // scrollHeight is never shorter than the iframe viewport, so using it
          // prevents an oversized fallback frame from shrinking. Every current
          // figure ends with its attribution; its lower edge is the intended
          // lower edge of the bordered iframe.
          const attribution = figureDocument.querySelector('.atlas-figure-attribution');
          const measured = attribution
            ? attribution.getBoundingClientRect().bottom +
              (figureDocument.defaultView?.scrollY || 0)
            : Math.max(
                figureDocument.body.scrollHeight,
                figureDocument.documentElement?.scrollHeight || 0,
              );
          if (measured > 0) frame.style.height = `${Math.max(320, Math.ceil(measured) + 2)}px`;
        };
        frame._atlasFigureObserver?.disconnect();
        resize();
        if ('ResizeObserver' in window) {
          frame._atlasFigureObserver = new ResizeObserver(resize);
          frame._atlasFigureObserver.observe(figureDocument.body);
        }
      } catch (error) {
        /* The fixed CSS height remains as the safe fallback. */
      }
    };
    document.querySelectorAll('iframe[data-atlas-figure]').forEach(frame => {
      frame.addEventListener('load', () => fitFigure(frame));
      if (frame.contentDocument?.readyState === 'complete') fitFigure(frame);
    });
  })();
</script>"""


def _page_document(
    config: AtlasConfig,
    active: str,
    page_name: str,
    description: str,
    content: str,
    updated: str,
    family: str,
    edition_notice: str | None = None,
    share: dict[str, Any] | None = None,
    publication_period: str | None = None,
    publication_complete: bool | None = None,
) -> str:
    # Generated tables use column headers throughout. Adding scope centrally keeps
    # screen-reader associations intact as new scientific panels are introduced.
    content = re.sub(r"<th(?![^>]*\bscope=)([^>]*)>", r'<th scope="col"\1>', content)
    outline = ""
    if family == "analysis":
        content, outline = _analysis_outline(content)
    title = config.project.name if active == "index.html" else f"{page_name} | {config.project.name}"
    notice_line = (
        f'  <div class="edition-notice" role="note">{html.escape(edition_notice)}</div>\n'
        if edition_notice
        else ""
    )
    report_family = {
        "home": "Project",
        "public": "Daily report",
        "analysis": "72-hour analysis",
        "archive": "Archive",
        "summary": "History",
        "records": "History",
    }[family]
    # A card always depicts one report period, so the control belongs only on the daily
    # report and the 72-hour analysis. The landing, summary, record and archive pages
    # cover no single period and would otherwise share a card describing something else.
    if family not in ("public", "analysis"):
        share = None
    share_id = "atlas-share-data" if share else None
    share_data_script = (
        f'<script type="application/json" id="{share_id}">'
        f'{json.dumps(json_ready(share), allow_nan=False)}</script>\n'
        if share
        else ""
    )
    publication = (
        _publication_strip(family, publication_period, updated, publication_complete is True)
        if publication_period and family in ("public", "analysis")
        else ""
    )
    shell_class = "page-shell with-outline" if outline else "page-shell"
    page_content = (
        f'<div class="page-layout"><div class="page-body">{content}</div>{outline}</div>'
        if outline
        else content
    )
    outline_script = """
  <script>
    const outlineLinks = Array.from(document.querySelectorAll('.page-outline a'));
    const outlineHeadings = outlineLinks
      .map(link => document.getElementById(link.hash.slice(1)))
      .filter(Boolean);
    if (outlineLinks.length && outlineHeadings.length && 'IntersectionObserver' in window) {
      const markCurrent = id => {
        outlineLinks.forEach(link => {
          const current = link.hash === `#${id}`;
          link.classList.toggle('current', current);
          if (current) link.setAttribute('aria-current', 'location');
          else link.removeAttribute('aria-current');
        });
      };
      const observer = new IntersectionObserver(entries => {
        const visible = entries
          .filter(entry => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) markCurrent(visible[0].target.id);
      }, { rootMargin: '-72px 0px -65% 0px', threshold: 0 });
      outlineHeadings.forEach(heading => observer.observe(heading));
      markCurrent(outlineHeadings[0].id);
    }
  </script>""" if outline else ""
    figure_resize_script = FIGURE_RESIZE_SCRIPT if "<iframe" in content else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <meta name="description" content="{html.escape(description)}">
  <link rel="dns-prefetch" href="//cdn.plot.ly">
{_social_meta(config, active, family, title, description)}  <style>{SHARED_CSS}{DATA_FIRST_CSS}</style>
</head>
<body>
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <div class="app-shell">
    <header class="site-header" id="site-navigation">{_navigation(active, family, share_id)}</header>
    <div class="sidebar-scrim" id="sidebar-scrim" aria-hidden="true"></div>
    <div class="workspace">
      <header class="report-topbar">
        <button class="menu-button" id="menu-button" type="button" aria-label="Open navigation" aria-controls="site-navigation" aria-expanded="false">&#9776;</button>
        <div class="breadcrumbs"><span class="optional">Atlas</span><span class="optional">/</span><span>{html.escape(report_family)}</span><span>/</span><strong>{html.escape(page_name)}</strong></div>
      </header>
{notice_line}      <main id="main-content" tabindex="-1"><div class="{shell_class}">{publication}{page_content}</div></main>
      <footer><div class="footer-wrap">Last updated {updated}. Debrecen weather with Hungary-wide electricity context.
        <span class="attribution">{SOURCE_ATTRIBUTION_HTML}</span>
      </div></footer>
    </div>
  </div>
  {share_data_script}<script>
    const navigation = document.querySelector('#site-navigation');
    const scrim = document.querySelector('#sidebar-scrim');
    const menuButton = document.querySelector('#menu-button');
    const mobileMenu = window.matchMedia('(max-width: 720px)');
    const setMenu = (open, restoreFocus = false) => {{
      navigation.classList.toggle('open', open);
      scrim.classList.toggle('open', open);
      menuButton.setAttribute('aria-expanded', String(open));
      menuButton.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
      if (mobileMenu.matches) {{
        navigation.setAttribute('aria-hidden', String(!open));
        navigation.toggleAttribute('inert', !open);
      }} else {{
        navigation.removeAttribute('aria-hidden');
        navigation.removeAttribute('inert');
      }}
      if (open && mobileMenu.matches) {{
        window.requestAnimationFrame(() => navigation.querySelector('a')?.focus());
      }} else if (restoreFocus) {{
        menuButton.focus();
      }}
    }};
    menuButton.addEventListener('click', () => setMenu(true));
    scrim.addEventListener('click', () => setMenu(false, true));
    navigation.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setMenu(false)));
    document.addEventListener('keydown', event => {{
      if (event.key === 'Escape' && navigation.classList.contains('open')) setMenu(false, true);
    }});
    mobileMenu.addEventListener?.('change', () => setMenu(false));
    setMenu(false);
  </script>
{outline_script}
  {figure_resize_script}
  {SHARE_SCRIPT if share_id else ""}
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


def _radar_cells_section(analysis: RadarCellAnalysis | None) -> str:
    """Convective cells tracked through the radar composite."""
    if analysis is None or not analysis.available:
        return ""
    track_rows = "".join(
        f"""
        <tr>
          <td>{track.identifier}</td>
          <td>{track.peak_dbz:.0f} dBZ</td>
          <td>{track.peak_area_km2:,.0f} km&sup2;</td>
          <td>{track.mean_speed_ms:.1f} m/s</td>
          <td>towards {track.bearing_deg:.0f}&deg;</td>
          <td>{track.closest_approach_km:,.0f} km</td>
          <td>{track.duration_hours:.1f} h</td>
        </tr>"""
        for track in analysis.tracks[:8]
    )
    coverage_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(item.label)}</td>
          <td>{f'{item.lower_dbz:.0f}+' if item.upper_dbz == float('inf') else f'{item.lower_dbz:.0f}&ndash;{item.upper_dbz:.0f}'} dBZ</td>
          <td>{item.peak_area_km2:,.0f} km&sup2;</td>
          <td>{item.mean_area_km2:,.0f} km&sup2;</td>
        </tr>"""
        for item in analysis.coverage
    )
    strongest = analysis.strongest
    nearest = analysis.nearest
    lead = "No cell met the tracking threshold during the period."
    if strongest is not None and nearest is not None:
        lead = (
            f"{len(analysis.tracks)} tracked cell(s) across {analysis.frames_analysed} frames. "
            f"The most intense peaked at {strongest.peak_dbz:.0f} dBZ moving "
            f"{strongest.mean_speed_ms:.1f} m/s towards {strongest.bearing_deg:.0f}&deg;, "
            f"and the nearest passed {nearest.closest_approach_km:,.0f} km from the city."
        )
    note_items = "".join(f"<li>{html.escape(note)}</li>" for note in analysis.notes)
    tracks_block = (
        f"""
  <h3 class="radar-subhead">Tracked cells</h3>
  <div class="table-scroll">
    <table>
      <thead><tr><th>Cell</th><th>Peak</th><th>Peak area</th><th>Mean speed</th><th>Direction</th><th>Closest approach</th><th>Tracked for</th></tr></thead>
      <tbody>{track_rows}</tbody>
    </table>
  </div>"""
        if track_rows
        else ""
    )
    return f"""
<section class="content-section">
  <h2>Radar Cell Tracking</h2>
  <p>{lead}</p>
  {tracks_block}
  <h3 class="radar-subhead">Echo coverage by intensity</h3>
  <div class="table-scroll">
    <table>
      <thead><tr><th>Class</th><th>Range</th><th>Peak area</th><th>Mean area</th></tr></thead>
      <tbody>{coverage_rows}</tbody>
    </table>
  </div>
  <ul class="verification-notes">{note_items}</ul>
</section>
"""


def _air_mass_origin_section(origin: AirMassOrigin | None) -> str:
    """Where the arriving air came from, traced backwards through the wind field."""
    if origin is None or not origin.available:
        return ""
    # Show the path coarsely: the whole hourly list is in the JSON download.
    stride = max(1, len(origin.points) // 8)
    milestones = [point for index, point in enumerate(origin.points) if index % stride == 0]
    if milestones[-1] is not origin.points[-1]:
        milestones.append(origin.points[-1])
    def coordinates(latitude: float, longitude: float) -> str:
        # West of Greenwich is well within the domain, so the hemisphere has to be
        # named rather than carried as a minus sign.
        return (
            f"{abs(latitude):.2f}&deg;{'N' if latitude >= 0 else 'S'}, "
            f"{abs(longitude):.2f}&deg;{'E' if longitude >= 0 else 'W'}"
        )

    rows = "".join(
        f"""
        <tr>
          <td>{point.hours_before_arrival:.0f} h</td>
          <td>{coordinates(point.latitude, point.longitude)}</td>
          <td>{point.distance_from_city_km:,.0f} km</td>
          <td>{'n/a' if not point.temperature_c == point.temperature_c else f'{point.temperature_c:.1f} &deg;C'}</td>
        </tr>"""
        for point in milestones
    )
    note_items = "".join(f"<li>{html.escape(note)}</li>" for note in origin.notes)
    traced_note = (
        f"Traced {origin.hours_traced:.0f} of the {origin.hours_requested} hours requested."
        if origin.hours_traced < origin.hours_requested
        else f"Traced the full {origin.hours_requested} hours."
    )
    return f"""
<section class="content-section">
  <h2>Air-Mass Origin</h2>
  <p>{html.escape(origin.summary)} {html.escape(traced_note)}</p>
  <div class="diagnostic-ledger kinematics-motion">
    <div><span>Origin bearing</span><strong>{html.escape(origin.origin_sector.title())}</strong><em>{origin.origin_distance_km:,.0f} km away</em></div>
    <div><span>Path length</span><strong>{origin.path_length_km:,.0f} km</strong><em>{origin.hours_traced:.0f} hours traced</em></div>
    <div><span>Mean transport speed</span><strong>{origin.mean_speed_ms:.1f} m/s</strong><em>at {origin.level_hpa} hPa</em></div>
  </div>
  <div class="table-scroll">
    <table>
      <thead><tr><th>Hours before arrival</th><th>Position</th><th>Distance from city</th><th>Temperature</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <ul class="verification-notes">{note_items}</ul>
</section>
"""


def _storm_kinematics_section(kinematics: StormKinematics | None) -> str:
    """The numbers a forecaster reads off the hodograph.

    Sits directly under that plot, since it quantifies the curve rather than adding
    an independent diagnostic.
    """
    if kinematics is None or not kinematics.available:
        return ""
    motion_cells = "".join(
        f"<div><span>{html.escape(motion.label)}</span>"
        f"<strong>{motion.speed_ms:.1f} m/s</strong>"
        f"<em>towards {motion.direction_deg:.0f}&deg;</em></div>"
        for motion in kinematics.motions
    )
    shear_rows = "".join(
        f"<tr><td>{html.escape(layer.label)}</td>"
        f"<td>{layer.magnitude_ms:.1f} m/s</td>"
        f"<td>{layer.u_ms:+.1f} m/s</td>"
        f"<td>{layer.v_ms:+.1f} m/s</td></tr>"
        for layer in kinematics.shear
    )
    helicity_rows = "".join(
        f"<tr><td>{html.escape(layer.label)}</td>"
        f"<td>{layer.total_m2_s2:+.0f}</td>"
        f"<td>{layer.positive_m2_s2:+.0f}</td>"
        f"<td>{layer.negative_m2_s2:+.0f}</td></tr>"
        for layer in kinematics.helicity
    )
    note_items = "".join(f"<li>{html.escape(note)}</li>" for note in kinematics.notes)
    tables = ""
    if shear_rows:
        tables += f"""
  <div class="kinematics-table">
    <h3>Bulk shear</h3>
    <div class="table-scroll">
      <table>
        <thead><tr><th>Layer</th><th>Magnitude</th><th>Eastward</th><th>Northward</th></tr></thead>
        <tbody>{shear_rows}</tbody>
      </table>
    </div>
  </div>"""
    if helicity_rows:
        tables += f"""
  <div class="kinematics-table">
    <h3>Storm-relative helicity <span>m&sup2;/s&sup2;</span></h3>
    <div class="table-scroll">
      <table>
        <thead><tr><th>Layer</th><th>Total</th><th>Positive</th><th>Negative</th></tr></thead>
        <tbody>{helicity_rows}</tbody>
      </table>
    </div>
  </div>"""
    motion_block = f'<div class="diagnostic-ledger kinematics-motion">{motion_cells}</div>' if motion_cells else ""
    return f"""
<section class="content-section">
  <h2>Storm-Relative Parameters</h2>
  <p>Derived from the same profile as the hodograph above. Storm motion follows Bunkers,
  and directions state where the storm would travel towards rather than where wind comes from.</p>
  {motion_block}
  <div class="kinematics-grid">{tables}</div>
  <ul class="verification-notes">{note_items}</ul>
</section>
"""


def _observational_coverage_section(coverages: list[InputCoverage] | None) -> str:
    """Per-day coverage for the observational inputs.

    Station and radar fail at opposite ends of the window: the station export
    regenerates once a day and can lag the trailing edge, while the radar archive
    retains only about seventy-one hours and loses the leading edge. An aggregate
    percentage hides both, so each day is shown on its own.
    """
    if not coverages:
        return ""
    blocks: list[str] = []
    for coverage in coverages:
        if coverage.per_day.empty:
            state = "Available" if coverage.available else "Unavailable"
            blocks.append(
                f'<div class="coverage-block"><h3>{html.escape(coverage.name.title())}</h3>'
                f"<p>{state}. {html.escape(' '.join(coverage.notes))}</p></div>"
            )
            continue
        cells = "".join(
            f'<div class="coverage-day" data-thin="{str(row.coverage < coverage.threshold).lower()}">'
            f"<span>{row.local_day}</span>"
            f"<strong>{row.coverage:.0%}</strong>"
            f"<em>{int(row.observed)}/{int(row.expected)}</em></div>"
            for row in coverage.per_day.itertuples()
        )
        headline = (
            f"{coverage.observed}/{coverage.expected} ({coverage.coverage:.0%}) against a "
            f"{coverage.threshold:.0%} threshold"
        )
        note_items = "".join(f"<li>{html.escape(note)}</li>" for note in coverage.notes)
        blocks.append(
            f'<div class="coverage-block"><h3>{html.escape(coverage.name.title())}</h3>'
            f"<p>{html.escape(headline)}</p>"
            f'<div class="coverage-days">{cells}</div>'
            f'<ul class="verification-notes">{note_items}</ul></div>'
        )
    return f"""
<section class="content-section">
  <h2>Observational Coverage</h2>
  <p>How much of the reporting window each observational input actually covers, by local day.
  A day below its threshold is marked.</p>
  <div class="coverage-grid">{"".join(blocks)}</div>
</section>
"""


def _verification_section(verification: StationVerification | None) -> str:
    """Reanalysis-versus-instrument scores for the period.

    Every other page treats the reanalysis as truth; this one states how far it sat
    from the station, so the reader can weight the rest accordingly.
    """
    if verification is None or not verification.variables:
        return ""
    rows = "".join(
        f"""
        <tr>
          <td>{html.escape(variable.label)}</td>
          <td class="verification-bias" data-sign="{'high' if variable.bias > 0 else 'low' if variable.bias < 0 else 'level'}">
            {variable.bias:+.2f} {html.escape(variable.unit)}
          </td>
          <td>{variable.mean_absolute_error:.2f} {html.escape(variable.unit)}</td>
          <td>{variable.root_mean_square_error:.2f} {html.escape(variable.unit)}</td>
          <td>{'n/a' if variable.correlation is None else f'{variable.correlation:.3f}'}</td>
          <td>{variable.pairs}{'' if variable.reliable else ' *'}</td>
        </tr>"""
        for variable in verification.variables
    )
    headline = verification.headline
    summary = ""
    if headline is not None:
        direction = "above" if headline.bias > 0 else "below" if headline.bias < 0 else "level with"
        summary = (
            f"Over {verification.hours_compared} paired hours the reanalysis ran "
            f"{abs(headline.bias):.2f} {headline.unit} {direction} the instrument on "
            f"{headline.label.lower()}, with a typical absolute miss of "
            f"{headline.mean_absolute_error:.2f} {headline.unit}."
        )
    note_items = "".join(f"<li>{html.escape(note)}</li>" for note in verification.notes)
    return f"""
<section class="content-section">
  <h2>Reanalysis Verification</h2>
  <p>Hourly ERA5 values against {html.escape(verification.station_name)} over the same hours.
  Bias is reanalysis minus station, so a positive figure means the reanalysis read high.
  {html.escape(summary)}</p>
  <div class="table-scroll">
    <table>
      <thead><tr><th>Variable</th><th>Bias</th><th>Mean absolute error</th><th>RMSE</th><th>Correlation</th><th>Paired hours</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <ul class="verification-notes">{note_items}</ul>
</section>
"""


def _weather_story_graph(story: WeatherStory) -> str:
    story_json = json.dumps(json_ready(asdict(story)), allow_nan=False).replace("<", "\\u003c")
    return f"""
<section class="story-section" id="weather-story">
  <header class="story-heading">
    <h2>{html.escape(story.title)}</h2>
    <div class="story-legend" aria-label="Weather story node categories">
      <span><i class="story-dot synoptic" aria-hidden="true"></i>Atmospheric setup</span>
      <span><i class="story-dot observed" aria-hidden="true"></i>Observed weather</span>
      <span><i class="story-dot impact" aria-hidden="true"></i>Land and energy impact</span>
    </div>
  </header>
  <div class="story-layout">
    <div class="story-field" aria-label="Interactive weather story relationships">
      <svg class="story-edges" aria-hidden="true">
        <defs><marker id="story-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>
      </svg>
      <div class="story-nodes"></div>
    </div>
    <aside class="story-evidence" aria-live="polite"></aside>
  </div>
  <p class="story-caption">Every node is generated from the report evidence. Arrows express deterministic dependence or an explicitly tested temporal relationship, not statistical causality.</p>
</section>
<script type="application/json" id="weather-story-data">{story_json}</script>
<script>
(() => {{
  const root = document.querySelector('#weather-story');
  if (!root) return;
  const data = JSON.parse(document.querySelector('#weather-story-data').textContent);
  const field = root.querySelector('.story-field');
  const svg = root.querySelector('.story-edges');
  const nodeLayer = root.querySelector('.story-nodes');
  const evidence = root.querySelector('.story-evidence');
  const buttons = new Map();

  const element = (tag, className, text) => {{
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
  }};

  const selectNode = node => {{
    buttons.forEach((button, id) => button.setAttribute('aria-pressed', String(id === node.id)));
    evidence.replaceChildren();
    // Three columns, so the panel reads across the full width under the graph.
    const reading = element('div', 'story-evidence-column');
    reading.append(element('div', 'story-evidence-domain', node.domain_label));
    reading.append(element('h3', '', node.label));
    reading.append(element('p', 'story-reading', node.reading));
    evidence.append(reading);

    const measures = element('div', 'story-evidence-column');
    const facts = element('dl', 'story-facts');
    node.facts.forEach(fact => {{
      const row = document.createElement('div');
      row.append(element('dt', '', fact.label));
      row.append(element('dd', '', fact.value));
      facts.append(row);
    }});
    measures.append(facts);
    measures.append(element('div', 'story-source', node.source));
    evidence.append(measures);

    const related = data.edges.filter(edge => edge.source === node.id || edge.target === node.id);
    const links = element('div', 'story-evidence-column');
    if (related.length) {{
      const connections = element('div', 'story-connections');
      connections.append(element('strong', '', 'Connections'));
      const list = document.createElement('ul');
      related.forEach(edge => {{
        const peerId = edge.source === node.id ? edge.target : edge.source;
        const peer = data.nodes.find(candidate => candidate.id === peerId);
        const direction = edge.source === node.id ? 'To' : 'From';
        list.append(element('li', '', `${{direction}} ${{peer.label}}: ${{edge.relationship}}.`));
      }});
      connections.append(list);
      links.append(connections);
    }}
    evidence.append(links);
  }};

  data.nodes.forEach(node => {{
    const button = element('button', 'story-node');
    button.type = 'button';
    button.dataset.domain = node.domain;
    button.setAttribute('aria-pressed', 'false');
    button.setAttribute('aria-label', `${{node.domain_label}}: ${{node.label}}`);
    button.append(element('span', 'story-node-domain', node.domain_label));
    button.append(element('span', 'story-node-label', node.label));
    button.addEventListener('click', () => selectNode(node));
    nodeLayer.append(button);
    buttons.set(node.id, button);
  }});

  const xs = data.nodes.map(node => node.x);
  const ys = data.nodes.map(node => node.y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const spanX = (Math.max(...xs) - minX) || 1;
  const spanY = (Math.max(...ys) - minY) || 1;

  const draw = () => {{
    const width = field.clientWidth;
    const height = field.clientHeight;
    const narrow = width < 620;
    const positions = new Map();
    // Cards are centred on their coordinate, so a raw fraction of the field pushes
    // half a card past the edge and `overflow: hidden` shears it off. Both layouts
    // place cards inside the box they actually fit in, measured from a real card
    // rather than assumed, which also reclaims the unused band below the graph.
    const sample = buttons.values().next().value;
    const halfWidth = (sample ? sample.offsetWidth : 170) / 2;
    const halfHeight = (sample ? sample.offsetHeight : 60) / 2;
    const inset = 10;
    const left = halfWidth + inset;
    const right = Math.max(left, width - halfWidth - inset);
    const top = halfHeight + inset;
    const bottom = Math.max(top, height - halfHeight - inset);
    if (narrow) {{
      const order = ['regime', 'sky', 'thermal', 'events', 'front', 'boundary', 'pv', 'land', 'wind'];
      const rows = Math.ceil(order.length / 2);
      const step = rows > 1 ? (bottom - top) / (rows - 1) : 0;
      order.forEach((id, index) => positions.set(id, {{
        x: index % 2 ? right : left,
        y: top + Math.floor(index / 2) * step,
      }}));
    }} else {{
      // The authored fractions span roughly .11-.86 across and .18-.80 down, so using
      // them directly leaves idle strips on both sides and a dead band underneath.
      // Stretching them across their own extent makes the graph fill the panel.
      data.nodes.forEach(node => positions.set(node.id, {{
        x: left + (node.x - minX) / spanX * (right - left),
        y: top + (node.y - minY) / spanY * (bottom - top),
      }}));
    }}
    // Stretching the coordinates can bring neighbours within a card's width of each
    // other, so push any overlapping pair apart along whichever axis needs least
    // movement, then pull everything back inside the field.
    const ids = data.nodes.map(node => node.id);
    const cardOf = id => buttons.get(id);
    for (let pass = 0; pass < 40; pass++) {{
      let moved = false;
      for (let i = 0; i < ids.length; i++) {{
        for (let j = i + 1; j < ids.length; j++) {{
          const a = positions.get(ids[i]);
          const b = positions.get(ids[j]);
          const cardA = cardOf(ids[i]);
          const cardB = cardOf(ids[j]);
          if (!a || !b || !cardA || !cardB) continue;
          const needX = (cardA.offsetWidth + cardB.offsetWidth) / 2 + 16;
          const needY = (cardA.offsetHeight + cardB.offsetHeight) / 2 + 14;
          const gapX = b.x - a.x;
          const gapY = b.y - a.y;
          const overlapX = needX - Math.abs(gapX);
          const overlapY = needY - Math.abs(gapY);
          if (overlapX <= 0 || overlapY <= 0) continue;
          moved = true;
          if (overlapX / needX <= overlapY / needY) {{
            const shift = (overlapX / 2) * (gapX < 0 ? -1 : 1);
            a.x -= shift;
            b.x += shift;
          }} else {{
            const shift = (overlapY / 2) * (gapY < 0 ? -1 : 1);
            a.y -= shift;
            b.y += shift;
          }}
        }}
      }}
      ids.forEach(id => {{
        const position = positions.get(id);
        if (!position) return;
        position.x = Math.min(Math.max(position.x, left), right);
        position.y = Math.min(Math.max(position.y, top), bottom);
      }});
      if (!moved) break;
    }}

    data.nodes.forEach(node => {{
      const position = positions.get(node.id);
      const button = buttons.get(node.id);
      button.style.left = `${{position.x}}px`;
      button.style.top = `${{position.y}}px`;
    }});
    svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);
    svg.querySelectorAll('.story-link').forEach(path => path.remove());
    // Every arrow leaves and lands on the midpoint of a card's side. Cards are
    // rectangles, so the side is chosen by comparing the run against the card's own
    // aspect: a link that travels more across than down uses a vertical side,
    // otherwise the top or bottom edge.
    const pickSide = (id, towardX, towardY) => {{
      const card = cardOf(id);
      const halfW = (card ? card.offsetWidth : 170) / 2;
      const halfH = (card ? card.offsetHeight : 58) / 2;
      if (Math.abs(towardX) * halfH >= Math.abs(towardY) * halfW) {{
        return towardX < 0 ? 'left' : 'right';
      }}
      return towardY < 0 ? 'top' : 'bottom';
    }};
    const sidePoint = (id, centre, side) => {{
      const card = cardOf(id);
      const halfW = (card ? card.offsetWidth : 170) / 2;
      const halfH = (card ? card.offsetHeight : 58) / 2;
      if (side === 'left') return {{x: centre.x - halfW, y: centre.y}};
      if (side === 'right') return {{x: centre.x + halfW, y: centre.y}};
      if (side === 'top') return {{x: centre.x, y: centre.y - halfH}};
      return {{x: centre.x, y: centre.y + halfH}};
    }};
    // A card's outgoing arrows all leave through one side, chosen from where its
    // targets sit on average, so the links read as a single fan rather than
    // sprouting from three different edges of the same card.
    const bearing = new Map();
    data.edges.forEach(edge => {{
      const start = positions.get(edge.source);
      const end = positions.get(edge.target);
      if (!start || !end) return;
      const dx = end.x - start.x;
      const dy = end.y - start.y;
      const run = Math.hypot(dx, dy) || 1;
      const acc = bearing.get(edge.source) || {{x: 0, y: 0}};
      acc.x += dx / run;
      acc.y += dy / run;
      bearing.set(edge.source, acc);
    }});
    const exitSide = new Map();
    bearing.forEach((acc, id) => exitSide.set(id, pickSide(id, acc.x, acc.y)));

    data.edges.forEach(edge => {{
      const start = positions.get(edge.source);
      const end = positions.get(edge.target);
      if (!start || !end) return;
      const dx = end.x - start.x;
      const dy = end.y - start.y;
      if (!dx && !dy) return;
      const from = sidePoint(edge.source, start, exitSide.get(edge.source) || pickSide(edge.source, dx, dy));
      const to = sidePoint(edge.target, end, pickSide(edge.target, -dx, -dy));
      const runX = to.x - from.x;
      const runY = to.y - from.y;
      const run = Math.hypot(runX, runY);
      if (run < 14) return;
      // Stop short of the border so the arrowhead points at the side midpoint
      // instead of overlapping the card. The gap also clears the 4px selection ring,
      // which otherwise covers the head of every arrow into the selected card.
      const gap = Math.min(15, run / 3);
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.classList.add('story-link');
      path.setAttribute('d', `M ${{from.x}} ${{from.y}} L ${{to.x - runX / run * gap}} ${{to.y - runY / run * gap}}`);
      svg.append(path);
    }});
  }};

  new ResizeObserver(draw).observe(field);
  selectNode(data.nodes[0]);
  draw();
}})();
</script>
"""


ARCHIVE_COMPAT_CSS = """
.archived-legacy-content > header {
  background: var(--paper);
  border: 0;
}
.archived-legacy-content > header .wrap,
.archived-legacy-content main .wrap {
  width: min(100%, 1320px);
  max-width: none;
  margin: 0 auto;
  padding: 34px 48px;
}
.archived-legacy-content > header .hero {
  min-height: 0;
  display: block;
  padding-bottom: 12px;
}
.archived-legacy-content > header .hero h1 {
  margin: 0 0 8px;
  font-size: 31px;
  font-weight: 620;
  line-height: 1.2;
}
.archived-legacy-content > header .hero h2 {
  margin: 0 0 5px;
  font-size: 15px;
  font-weight: 650;
}
.archived-legacy-content > header .hero .brief {
  max-width: 940px;
  margin: 0;
  color: var(--ink-soft);
  font-size: 14px;
  line-height: 1.62;
}
.archived-legacy-content .summary {
  gap: 0;
  margin-top: 24px;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
}
.archived-legacy-content main .wrap { display: block; }
.archived-legacy-content main section,
.archived-legacy-content .table-panel {
  max-width: 100%;
  margin: 0;
  padding: 24px 0 34px;
  background: transparent;
  border: 0;
  border-top: 1px solid var(--line);
  border-radius: 0;
  box-shadow: none;
  overflow-x: auto;
}
.archived-legacy-content .grid-two,
.archived-legacy-content .notes {
  display: block;
}
.archived-legacy-content .viz-frame {
  border-color: var(--line-strong);
  border-radius: 5px;
}
.archived-legacy-content .viz-frame.tall { min-height: 900px; }
.archived-legacy-content footer .wrap {
  width: min(100%, 1320px);
  margin: 0 auto;
  padding: 18px 48px;
  font-size: 11px;
}
@media (max-width: 720px) {
  .archived-legacy-content > header .wrap,
  .archived-legacy-content main .wrap { padding: 28px 20px 56px; }
  .archived-legacy-content > header .hero h1 { font-size: 28px; }
  .archived-legacy-content .summary { grid-template-columns: 1fr; }
  .archived-legacy-content footer .wrap { padding: 18px 20px; }
}
"""


def _saved_report_directories(parent: Path) -> list[Path]:
    if not parent.is_dir():
        return []
    return sorted(
        (
            path
            for path in parent.iterdir()
            if path.is_dir() and (path / "index.html").is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )


def _archive_date_label(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    return f"{parsed.day} {parsed.strftime('%B %Y')}"


def _archive_entry(source: Path, collection: str) -> dict[str, Any]:
    slug = source.name
    if collection == "daily":
        start = end = slug
        date_label = _archive_date_label(slug)
        coverage = "One complete local day"
        edition = "Public report"
        href = f"daily/{slug}/index.html"
    else:
        start, end = slug.split("_", maxsplit=1)
        date_label = f"{_archive_date_label(start)} - {_archive_date_label(end)}"
        day_count = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1
        if collection == "periods":
            coverage = f"{day_count}-day rolling window"
            edition = "Meteorological analysis"
            href = (
                f"periods/{slug}/analysis/index.html"
                if (source / "analysis" / "index.html").is_file()
                else f"periods/{slug}/index.html"
            )
        else:
            coverage = f"{day_count}-day historical window"
            edition = "Legacy weekly report"
            href = f"weeks/{slug}/index.html"

    page_count = len(list(source.glob("*.html")))
    if (source / "analysis").is_dir():
        page_count += len(list((source / "analysis").glob("*.html")))
    return {
        "source": source,
        "slug": slug,
        "year": start[:4],
        "date_label": date_label,
        "coverage": coverage,
        "edition": edition,
        "page_count": page_count,
        "href": href,
        "start": start,
        "end": end,
    }


def _archived_navigation(
    active: str,
    page_dir: Path,
    family: str,
    archive_href: str,
    root_prefix: str = "",
) -> tuple[str, str]:
    if family == "public":
        candidates = ARCHIVED_PUBLIC_PAGES
        family_label = "Saved daily report"
    elif family == "analysis" and root_prefix:
        candidates = ANALYSIS_PAGES
        family_label = "Saved 72-hour analysis"
    elif family == "analysis":
        candidates = LEGACY_ANALYSIS_PAGES
        family_label = "Saved 72-hour analysis"
    else:
        candidates = (("index.html", "Overview"),)
        family_label = "Saved weekly report"

    pages = [(filename, label) for filename, label in candidates if (page_dir / filename).is_file()]
    page_name = dict(pages).get(active, Path(active).stem.replace("-", " ").title())
    links = []
    for filename, label in pages:
        current = ' aria-current="page"' if filename == active else ""
        links.append(f'<a href="{filename}"{current}>{html.escape(label)}</a>')

    # An archived edition remains part of Archive even when it is a daily or
    # 72-hour report. The three global destinations therefore always return to
    # the live publications or the archive root, while the secondary list moves
    # within the preserved edition.
    live_root = f'{archive_href.removesuffix("index.html")}../'
    navigation = (
        f'<div class="nav-wrap"><a class="brand" href="{html.escape(live_root)}index.html">Atlas</a>'
        f'<span class="nav-label">Publications</span>'
        f'<nav class="report-switch" aria-label="Atlas publications">'
        f'<a href="{html.escape(live_root)}report.html">Daily Report</a>'
        f'<a href="{html.escape(live_root)}analysis/index.html">72-Hour Analysis</a>'
        f'<a href="{html.escape(archive_href)}" aria-current="true">Archive</a></nav>'
        f'<span class="nav-label">{family_label}</span>'
        f'<nav class="primary-nav" aria-label="Primary">{"".join(links)}</nav>'
        f'<div class="sidebar-note"><strong>Debrecen, Hungary</strong>'
        f'Archived meteorological record. Values and interpretation are preserved.</div></div>'
    )
    return navigation, page_name


def _ensure_archived_publication_strip(
    document: str,
    page: Path,
    family: str,
) -> str:
    if 'class="publication-state"' in document:
        return document
    edition_dir = page.parent.parent if page.parent.name == "analysis" else page.parent
    period = edition_dir.name.replace("_", " to ")
    updated_match = re.search(r"Last updated\s+([^.<]+(?:UTC|CEST|CET)?)", document)
    updated = updated_match.group(1).strip() if updated_match else "Preserved edition"
    complete = "data-atlas-erratum" not in document
    strip = _publication_strip(family, period, updated, complete)
    shell = re.compile(r'(<div class="page-shell(?: [^"]*)?">)')
    if shell.search(document):
        return shell.sub(lambda match: f"{match.group(1)}{strip}", document, count=1)
    return re.sub(
        r"(<main\b[^>]*>)",
        lambda match: f"{match.group(1)}{strip}",
        document,
        count=1,
    )


def _enhance_archived_document(document: str) -> str:
    """Add low-risk accessibility and loading hints to preserved outer pages."""
    if "<body" not in document:
        return document
    marker = "data-atlas-archive-accessibility"
    if marker not in document:
        patch_css = """
<style data-atlas-archive-accessibility>
:root{--muted:#66645f;--blue:#315f8d;--green:#2f6f58;--gold:#8a5b16;--red:#a83b33}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.skip-link{position:fixed;top:8px;left:8px;z-index:100;padding:9px 12px;color:#fff;background:#232323;border-radius:4px;transform:translateY(-160%)}
.skip-link:focus{transform:translateY(0)}
:where(a,button,input,select,summary,[tabindex]):focus-visible{outline:3px solid #3f72a4;outline-offset:3px}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
</style>
"""
        document = document.replace("</head>", f"{patch_css}</head>", 1)
        document = re.sub(
            r"(<body[^>]*>)",
            r'\1<a class="skip-link" href="#main-content">Skip to main content</a>',
            document,
            count=1,
        )

    document = re.sub(
        r"<main(?![^>]*\bid=)([^>]*)>",
        r'<main id="main-content" tabindex="-1"\1>',
        document,
        count=1,
    )
    document = re.sub(r"<th(?![^>]*\bscope=)([^>]*)>", r'<th scope="col"\1>', document)

    def iframe_hints(match: re.Match[str]) -> str:
        tag = match.group(0)
        if " loading=" not in tag:
            tag = tag[:-1] + ' loading="lazy">'
        if " title=" not in tag:
            tag = tag[:-1] + ' title="Interactive data figure">'
        if " data-atlas-figure" not in tag:
            tag = tag[:-1] + " data-atlas-figure>"
        return tag

    def image_hints(match: re.Match[str]) -> str:
        tag = match.group(0)
        if " loading=" not in tag:
            tag = tag[:-1] + ' loading="lazy">'
        if " decoding=" not in tag:
            tag = tag[:-1] + ' decoding="async">'
        return tag

    document = re.sub(r"<iframe\b[^>]*>", iframe_hints, document, flags=re.I)
    document = re.sub(r"<img\b[^>]*>", image_hints, document, flags=re.I)
    if "<iframe" in document and "data-atlas-figure-resize" not in document:
        document = document.replace("</body>", f"{FIGURE_RESIZE_SCRIPT}</body>", 1)
    if 'id="menu-button"' in document:
        document = re.sub(
            r'(<button\b[^>]*id="menu-button"[^>]*)(>)',
            lambda match: (
                match.group(1)
                + (' aria-controls="site-navigation"' if "aria-controls=" not in match.group(1) else "")
                + (' aria-expanded="false"' if "aria-expanded=" not in match.group(1) else "")
                + match.group(2)
            ),
            document,
            count=1,
        )
        if "menuButton.setAttribute('aria-expanded'" not in document:
            menu_patch = """
<script data-atlas-archive-menu-accessibility>
(() => {
  const nav = document.querySelector('#site-navigation');
  const scrim = document.querySelector('#sidebar-scrim');
  const button = document.querySelector('#menu-button');
  if (!nav || !button) return;
  const sync = () => {
    const open = nav.classList.contains('open');
    button.setAttribute('aria-expanded', String(open));
    button.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  };
  button.addEventListener('click', () => requestAnimationFrame(sync));
  scrim?.addEventListener('click', () => requestAnimationFrame(sync));
  nav.querySelectorAll('a').forEach(link => link.addEventListener('click', () => requestAnimationFrame(sync)));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && nav.classList.contains('open')) {
      nav.classList.remove('open');
      scrim?.classList.remove('open');
      sync();
      button.focus();
    }
  });
  sync();
})();
</script>
"""
            document = document.replace("</body>", f"{menu_patch}</body>", 1)
    return document


def _restyle_archived_document(
    document: str,
    page: Path,
    family: str,
    archive_href: str,
    root_prefix: str = "",
) -> str:
    navigation, page_name = _archived_navigation(
        page.name,
        page.parent,
        family,
        archive_href,
        root_prefix,
    )
    if 'class="app-shell"' in document:
        document = re.sub(
            r'<header class="site-header"[^>]*>.*?</header>',
            f'<header class="site-header" id="site-navigation">{navigation}</header>',
            document,
            count=1,
            flags=re.DOTALL,
        )
        if ".publication-state {" not in document:
            document = document.replace(
                "</head>",
                f'<style data-atlas-archive-current-design>{DATA_FIRST_CSS}</style></head>',
                1,
            )
        document = _ensure_archived_publication_strip(document, page, family)
        return _enhance_archived_document(document)
    if "<body>" not in document:
        return _enhance_archived_document(document)
    family_label = {
        "public": "Daily report",
        "analysis": "72-hour analysis",
        "weekly": "Weekly report",
    }[family]
    shell_start = f"""
  <div class="app-shell" data-atlas-restyled="true">
    <header class="site-header" id="site-navigation">{navigation}</header>
    <div class="sidebar-scrim" id="sidebar-scrim" aria-hidden="true"></div>
    <div class="workspace">
      <header class="report-topbar">
        <button class="menu-button" id="menu-button" type="button" aria-label="Open navigation" aria-controls="site-navigation" aria-expanded="false">&#9776;</button>
        <div class="breadcrumbs"><span class="optional">Atlas</span><span class="optional">/</span><span>Archive</span><span>/</span><span>{html.escape(family_label)}</span><span>/</span><strong>{html.escape(page_name)}</strong></div>
      </header>
"""
    current_styles = f"<style>{SHARED_CSS}{DATA_FIRST_CSS}{ARCHIVE_COMPAT_CSS}</style>"
    document = document.replace("</head>", f"{current_styles}\n</head>", 1)
    document = document.replace("<body>", '<body data-atlas-archive-page="true">', 1)

    old_navigation = re.compile(
        r'\s*<header class="site-header"[^>]*>.*?</header>',
        flags=re.DOTALL,
    )
    if old_navigation.search(document):
        document = old_navigation.sub(shell_start, document, count=1)
        legacy_close = ""
    else:
        document = document.replace(
            '<body data-atlas-archive-page="true">',
            f'<body data-atlas-archive-page="true">{shell_start}<div class="archived-legacy-content">',
            1,
        )
        legacy_close = "</div>"

    menu_script = """
      <script>
        const navigation = document.querySelector('#site-navigation');
        const scrim = document.querySelector('#sidebar-scrim');
        const menuButton = document.querySelector('#menu-button');
        const setMenu = open => {
          navigation.classList.toggle('open', open);
          scrim.classList.toggle('open', open);
          menuButton.setAttribute('aria-expanded', String(open));
          menuButton.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
        };
        menuButton.addEventListener('click', () => setMenu(true));
        scrim.addEventListener('click', () => setMenu(false));
        navigation.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setMenu(false)));
        document.addEventListener('keydown', event => {
          if (event.key === 'Escape' && navigation.classList.contains('open')) {
            setMenu(false);
            menuButton.focus();
          }
        });
      </script>
"""
    document = document.replace(
        "</body>",
        f"{legacy_close}{menu_script}    </div>\n  </div>\n</body>",
        1,
    )
    document = _ensure_archived_publication_strip(document, page, family)
    return _enhance_archived_document(document)


def _rewrite_published_archive_links(target: Path, collection: str) -> None:
    analysis_dir = target / "analysis"
    root_family = (
        "public"
        if collection == "daily" or analysis_dir.is_dir()
        else ("weekly" if collection == "weeks" else "analysis")
    )
    for page in target.glob("*.html"):
        document = page.read_text(encoding="utf-8")
        document = document.replace('href="archive/index.html"', 'href="../../index.html"')
        if collection == "daily":
            document = document.replace(
                'href="analysis/index.html"',
                'href="../../index.html#analysis-reports"',
            )
            document = document.replace('href="report.html"', 'href="index.html"')
        document = _restyle_archived_document(
            document,
            page,
            root_family,
            "../../index.html",
        )
        page.write_text(document, encoding="utf-8")

    if analysis_dir.is_dir():
        for page in analysis_dir.glob("*.html"):
            document = page.read_text(encoding="utf-8").replace(
                'href="../archive/index.html"',
                'href="../../../index.html"',
            )
            document = _restyle_archived_document(
                document,
                page,
                "analysis",
                "../../../index.html",
                "../",
            )
            page.write_text(document, encoding="utf-8")


def _archive_table(entries: list[dict[str, Any]], section_id: str, title: str) -> str:
    rows = "".join(
        f"""
        <tr data-archive-row data-year="{html.escape(entry['year'])}" data-search="{html.escape((entry['slug'] + ' ' + entry['edition']).lower())}">
          <td class="archive-date"><strong>{html.escape(entry['date_label'])}</strong><span>{html.escape(entry['slug'])}</span></td>
          <td>{html.escape(entry['edition'])}</td>
          <td>{html.escape(entry['coverage'])}; {entry['page_count']} saved page{'s' if entry['page_count'] != 1 else ''}</td>
          <td><a class="archive-open" href="{html.escape(entry['href'])}">Open report &rarr;</a></td>
        </tr>"""
        for entry in entries
    )
    table = f"""
      <div class="table-scroll">
        <table class="archive-table">
          <caption class="sr-only">{html.escape(title)}</caption>
          <thead><tr><th scope="col">Date</th><th scope="col">Edition</th><th scope="col">Coverage</th><th scope="col">Report</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>""" if rows else ""
    return f"""
<section class="archive-group" id="{html.escape(section_id)}" data-archive-group>
  <div class="archive-group-header"><h2>{html.escape(title)}</h2><span>{len(entries)} saved edition{'s' if len(entries) != 1 else ''}</span></div>
  {table}
  <p class="archive-empty">No saved reports match the current filter.</p>
</section>
"""


def collect_weather_event_index(
    reports_dir: Path,
    timezone_name: str = "Europe/Budapest",
) -> list[dict[str, Any]]:
    """Read and de-duplicate the objective event ledgers in saved periods."""
    required = {"start_time", "end_time", "kind", "evidence", "confidence", "source"}
    deduplicated: dict[tuple[str, str, str], dict[str, Any]] = {}
    periods_dir = reports_dir / "periods"
    if not periods_dir.is_dir():
        return []

    # Later rolling editions replace an overlapping event with their newer copy.
    for edition_dir in sorted(path for path in periods_dir.iterdir() if path.is_dir()):
        ledger = edition_dir / "data" / "weather_phenomena.csv"
        if not ledger.is_file():
            continue
        try:
            frame = pd.read_csv(ledger)
        except (OSError, pd.errors.ParserError):
            continue
        if not required.issubset(frame.columns):
            continue
        for row in frame.itertuples(index=False):
            try:
                start = pd.Timestamp(row.start_time)
                end = pd.Timestamp(row.end_time)
                if start.tzinfo is None or end.tzinfo is None:
                    continue
                start = start.tz_convert("UTC")
                end = end.tz_convert("UTC")
                confidence = float(row.confidence)
            except (TypeError, ValueError):
                continue
            if end <= start or not 0.0 <= confidence <= 1.0:
                continue
            if any(pd.isna(value) for value in (row.kind, row.evidence, row.source)):
                continue
            kind = str(row.kind).strip()
            evidence = str(row.evidence).strip()
            source = str(row.source).strip()
            if not kind or not evidence or not source:
                continue
            source_lower = source.lower()
            if "hungaromet" in source_lower:
                source_type = "Observed"
            elif "open-meteo" in source_lower:
                source_type = "Model-derived"
            elif "objective" in source_lower:
                source_type = "Derived"
            else:
                source_type = "Other"

            preferred_page = edition_dir / "analysis" / "storms-satellite.html"
            if preferred_page.is_file():
                report_page = "analysis/storms-satellite.html"
            elif (edition_dir / "events.html").is_file():
                report_page = "events.html"
            else:
                report_page = "index.html"
            local_start = start.tz_convert(timezone_name)
            local_end = end.tz_convert(timezone_name)
            key = (start.isoformat(), end.isoformat(), kind.casefold())
            deduplicated[key] = {
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "local_date": local_start.strftime("%Y-%m-%d"),
                "local_time": f"{local_start.strftime('%H:%M')}–{local_end.strftime('%H:%M %Z')}",
                "kind": kind,
                "evidence": evidence,
                "confidence": confidence,
                "source": source,
                "source_type": source_type,
                "edition": edition_dir.name,
                "report_href": f"periods/{edition_dir.name}/{report_page}",
            }

    return sorted(
        deduplicated.values(),
        key=lambda event: (event["start_time"], event["kind"]),
        reverse=True,
    )


def _weather_event_index(events: list[dict[str, Any]]) -> str:
    """Render event evidence as a searchable section inside the report archive."""
    rows = "".join(
        f"""
        <tr data-event-row data-search="{html.escape(' '.join((event['local_date'], event['kind'], event['evidence'], event['source'], event['source_type'], event['edition'])).casefold())}">
          <td class="archive-date"><strong><time datetime="{html.escape(event['start_time'])}">{html.escape(event['local_date'])}</time></strong><span>{html.escape(event['local_time'])}</span></td>
          <td><span class="event-kind">{html.escape(event['kind'])}</span><span class="event-source">{_evidence_badge(event['source_type'])} {html.escape(event['source'])}</span></td>
          <td class="event-evidence">{html.escape(event['evidence'])}</td>
          <td class="event-confidence">{event['confidence']:.0%}</td>
          <td><a class="archive-open" href="{html.escape(event['report_href'])}">Evidence &rarr;</a></td>
        </tr>"""
        for event in events
    )
    table = (
        f"""
  <div class="table-scroll">
    <table class="archive-table event-table">
      <caption class="sr-only">Detected weather events across saved Atlas editions</caption>
      <thead><tr><th scope="col">When</th><th scope="col">Event</th><th scope="col">Evidence</th><th scope="col">Confidence</th><th scope="col">Report</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>"""
        if rows
        else ""
    )
    empty = "true" if not events else "false"
    return f"""
<section class="archive-group" id="weather-event-index" data-event-group data-empty="{empty}">
  <div class="archive-group-header"><h2>Weather Event Index</h2><span>{len(events)} unique detection{'s' if len(events) != 1 else ''}</span></div>
  <p class="event-download">Objective detections de-duplicated across overlapping 72-hour reports. Times are Europe/Budapest local time. <a href="data/weather_event_index.json" download>Download JSON</a>.</p>
  {table}
  <p class="archive-empty">No weather events match the current search.</p>
</section>
"""
def build_report_archive(
    config: AtlasConfig,
    site_dir: Path | None = None,
    reports_dir: Path | None = None,
    updated: str | None = None,
) -> Path:
    site_dir = site_dir or config.outputs.site_dir
    reports_dir = reports_dir or config.outputs.reports_dir
    archive_dir = site_dir / "archive"
    with staged_directory(archive_dir) as staging_dir:
        _build_report_archive_into(
            config,
            site_dir,
            reports_dir,
            updated,
            staging_dir,
        )
    # This history now lives inside the Archive. Retire files from the earlier
    # standalone implementation only after the replacement archive is live.
    for stale in (site_dir / "event-atlas.html", site_dir / "data" / "event_atlas.json"):
        if stale.is_file():
            stale.unlink()
    return archive_dir / "index.html"


def _build_report_archive_into(
    config: AtlasConfig,
    site_dir: Path,
    reports_dir: Path,
    updated: str | None,
    archive_dir: Path,
) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)

    saved = {
        collection: _saved_report_directories(reports_dir / collection)
        for collection in ("daily", "periods", "weeks")
    }
    for collection, edition_dirs in saved.items():
        for edition_dir in edition_dirs:
            ensure_edition_bundle(
                edition_dir,
                collection,
                location_name=config.location.name,
                timezone_name=config.location.timezone,
                latitude=config.location.latitude,
                longitude=config.location.longitude,
            )
            validation = validate_edition_bundle(edition_dir)
            if not validation.valid:
                detail = "; ".join(validation.errors)
                raise ValueError(f"Invalid archive bundle {edition_dir.name}: {detail}")

    size_payload = archive_size_report(saved)

    collections = {
        collection: [_archive_entry(source, collection) for source in sources]
        for collection, sources in saved.items()
    }
    archive_figure_renderer = write_shared_figure_renderer(archive_dir)

    for collection, entries in collections.items():
        target_parent = archive_dir / collection
        for entry in entries:
            target = target_parent / entry["slug"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(entry["source"], target)
            _rewrite_published_archive_links(target, collection)
            manifest = json.loads(
                (entry["source"] / "manifest.json").read_text(encoding="utf-8")
            )
            publish_shared_figure_stubs(
                target,
                manifest.get("figures", []),
                archive_figure_renderer,
            )

    # Daily editions contain no copied observation ledger, so their historic
    # coverage defect is measured from the corresponding saved 72-hour period.
    # Applying the banner to the published copy preserves the source artefact
    # while ensuring the more public daily report carries the correction too.
    annotate_daily_from_periods(archive_dir / "daily", reports_dir / "periods")

    all_entries = [entry for entries in collections.values() for entry in entries]
    earliest = min((entry["start"] for entry in all_entries), default="n/a")
    total = len(all_entries)
    events = collect_weather_event_index(reports_dir, config.location.timezone)
    archive_data_dir = archive_dir / "data"
    archive_data_dir.mkdir(parents=True, exist_ok=True)
    (archive_data_dir / "weather_event_index.json").write_text(
        json.dumps({"events": events}, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    (archive_data_dir / "catalog.v1.json").write_text(
        json.dumps(
            build_archive_catalog(saved),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (archive_data_dir / "size-report.v1.json").write_text(
        json.dumps(
            size_payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    content = _page_intro(
        "Report Archive",
        "Search preserved public reports, meteorological analyses and their objective weather-event evidence in one place.",
        "Saved Atlas editions",
    )
    content += f"""
<div class="archive-summary" aria-label="Archive summary">
  <div class="archive-stat"><span>All editions</span><strong>{total}</strong><small>saved reports</small></div>
  <div class="archive-stat"><span>Daily public</span><strong>{len(collections['daily'])}</strong><small>complete local days</small></div>
  <div class="archive-stat"><span>72-hour analysis</span><strong>{len(collections['periods'])}</strong><small>rolling periods</small></div>
  <div class="archive-stat"><span>Record begins</span><strong>{html.escape(earliest)}</strong><small>earliest saved window</small></div>
</div>
<div class="archive-toolbar" aria-label="Search the archive">
  <label class="archive-control"><span>Search reports and events</span><input id="archive-search" type="search" placeholder="Date, thunderstorm, heat, gust, source…" autocomplete="off"></label>
  <div class="archive-visible-count" id="archive-visible-count" role="status" aria-live="polite">{total} reports · {len(events)} events</div>
</div>
"""
    content += _archive_table(collections["daily"], "daily-reports", "Daily Public Reports")
    content += _archive_table(collections["periods"], "analysis-reports", "72-Hour Meteorological Analysis")
    content += _archive_table(collections["weeks"], "weekly-reports", "Legacy Weekly Reports")
    content += _weather_event_index(events)
    content += """
<script>
  const archiveSearch = document.querySelector('#archive-search');
  const archiveRows = Array.from(document.querySelectorAll('[data-archive-row]'));
  const archiveGroups = Array.from(document.querySelectorAll('[data-archive-group]'));
  const eventRows = Array.from(document.querySelectorAll('[data-event-row]'));
  const eventGroup = document.querySelector('[data-event-group]');
  const archiveVisibleCount = document.querySelector('#archive-visible-count');
  const filterArchive = () => {
    const query = archiveSearch.value.trim().toLocaleLowerCase();
    let visibleReports = 0;
    let visibleEvents = 0;
    archiveRows.forEach(row => {
      row.hidden = Boolean(query && !row.dataset.search.includes(query));
      if (!row.hidden) visibleReports += 1;
    });
    archiveGroups.forEach(group => {
      const hasVisibleRows = Array.from(group.querySelectorAll('[data-archive-row]')).some(row => !row.hidden);
      group.dataset.empty = String(!hasVisibleRows);
    });
    eventRows.forEach(row => {
      row.hidden = Boolean(query && !row.dataset.search.includes(query));
      if (!row.hidden) visibleEvents += 1;
    });
    if (eventGroup) eventGroup.dataset.empty = String(!visibleEvents);
    archiveVisibleCount.textContent = `${visibleReports} report${visibleReports === 1 ? '' : 's'} · ${visibleEvents} event${visibleEvents === 1 ? '' : 's'}`;
  };
  archiveSearch.addEventListener('input', filterArchive);
  filterArchive();
</script>
"""

    updated = updated or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    index = archive_dir / "index.html"
    index.write_text(
        _page_document(
            config,
            "index.html",
            "Report Archive",
            "Search saved Debrecen reports and their weather-event evidence.",
            content,
            updated,
            "archive",
        ),
        encoding="utf-8",
    )
    externalize_repeated_archive_styles(archive_dir)
    enforce_published_archive_limits(archive_dir)
    return index


def archive_site(site_dir: Path, archive_dir: Path) -> Path:
    planned: dict[Path, Path] = {}
    for source in site_dir.iterdir():
        if source.name in {".gitkeep", "archive", "event-atlas.html"}:
            continue
        if source.is_dir():
            for child in source.rglob("*"):
                if not child.is_file():
                    continue
                relative = child.relative_to(site_dir)
                if relative.as_posix() == "data/event_atlas.json":
                    continue
                planned[relative] = child
        else:
            planned[Path(source.name)] = source
    if _preserve_identical_frozen_edition(archive_dir, planned):
        return archive_dir / "index.html"
    with staged_directory(archive_dir) as staging_dir:
        for relative, source in planned.items():
            target = staging_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return archive_dir / "index.html"


def archive_public_site(
    site_dir: Path,
    archive_dir: Path,
    asset_names: set[str],
    data_paths: set[Path] | None = None,
) -> Path:
    planned: dict[Path, Path] = {}
    for filename, _ in PUBLIC_PAGES:
        source = site_dir / filename
        if source.exists():
            target_name = "index.html" if filename == "report.html" else filename
            planned[Path(target_name)] = source
    for name in asset_names:
        source = site_dir / "assets" / name
        if source.exists():
            planned[Path("assets") / name] = source
    for source in sorted(data_paths or set(), key=lambda path: path.name):
        if source.is_file():
            relative = Path("data") / source.name
            if relative in planned:
                raise ValueError(f"Duplicate daily evidence filename: {source.name}")
            planned[relative] = source
    if _preserve_identical_frozen_edition(archive_dir, planned):
        return archive_dir / "index.html"
    with staged_directory(archive_dir) as staging_dir:
        for relative, source in planned.items():
            target = staging_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return archive_dir / "index.html"


def _preserve_identical_frozen_edition(
    archive_dir: Path,
    planned: dict[Path, Path],
) -> bool:
    """Keep an existing frozen edition only when the proposed capture is exact."""

    if not (archive_dir / "manifest.json").is_file():
        return False
    generated = {Path("manifest.json"), Path("narrative.json")}
    existing = {
        path.relative_to(archive_dir): path
        for path in archive_dir.rglob("*")
        if path.is_file()
        and path.relative_to(archive_dir) not in generated
        and path.relative_to(archive_dir).parts[0] != "bundle"
    }
    if set(existing) != set(planned) or any(
        existing[relative].read_bytes() != source.read_bytes()
        for relative, source in planned.items()
    ):
        raise ImmutableEditionError(
            f"Frozen edition {archive_dir.name} differs from the proposed capture; "
            "publish it under a new edition or run an explicit migration"
        )
    return True


def _record_line(record: RecordEntry | None) -> str:
    if record is None:
        return '<span class="muted-cell">n/a</span>'
    return f'{record.value:g} {html.escape(record.unit)}<span>{html.escape(record.on_date)}</span>'


def _almanac_period_panel(period: PeriodClimate) -> str:
    stats = f"""
    <div class="almanac-stats">
      <div><span>Mean temperature</span><strong>{period.mean_temperature_c:.1f}&deg;C</strong></div>
      <div><span>Typical precipitation</span><strong>{period.mean_precipitation_mm:.1f} mm</strong></div>
      <div><span>Mean wind speed</span><strong>{period.mean_wind_speed_ms:.1f} m/s</strong></div>
      <div><span>Mean cloud cover</span><strong>{period.mean_cloud_cover_pct:.0f}%</strong></div>
      <div><span>Typical solar energy</span><strong>{period.mean_shortwave_wh_m2:.0f} Wh/m&sup2;</strong></div>
      <div><span>Typical water balance</span><strong>{period.mean_water_balance_mm:.1f} mm</strong></div>
    </div>"""
    records = [
        record
        for record in (
            period.warmest_day,
            period.coldest_day,
            period.wettest_day,
            period.windiest_day,
            period.sunniest_day,
            period.driest_day,
        )
        if record is not None
    ]
    record_items = "".join(
        f'<li><strong>{html.escape(record.label)}</strong>{_record_line(record)}</li>' for record in records
    )
    return f"""
<section class="almanac-panel" data-summary-panel data-summary-kind="{html.escape(period.kind)}" data-summary-key="{html.escape(period.key)}" hidden>
  <div class="almanac-panel-header">
    <h2>{html.escape(period.name)}</h2>
    <span>{period.years} years of ERA5 daily data</span>
  </div>
  {stats}
  <h3>Records for {html.escape(period.name)}</h3>
  <ul class="almanac-records">{record_items}</ul>
</section>"""


def _almanac_pages(config: AtlasConfig, almanac: Almanac) -> tuple[str, str]:
    coverage = f"{almanac.archive_start_year}-{almanac.archive_end_year}"
    notes_items = "".join(f"<li>{html.escape(note)}</li>" for note in almanac.notes)

    # One control, not a mode switch plus two dropdowns: the option value carries the
    # kind, so months and seasons live in the same list under their own group headings.
    month_options = "".join(
        f'<option value="month:{html.escape(period.key)}">{html.escape(period.name)}</option>'
        for period in almanac.months
    )
    season_options = "".join(
        f'<option value="season:{html.escape(period.key)}">{html.escape(period.name)}</option>'
        for period in almanac.seasons
    )
    panels = "".join(_almanac_period_panel(period) for period in [*almanac.months, *almanac.seasons])

    summary_content = f"""{_page_intro(
        "Season & Month Summary",
        f"Climatological digests built from {almanac.total_days} daily ERA5 values for "
        f"{config.location.name} across {coverage}. Selecting a month or season reads data already "
        "generated for this site; nothing is fetched on demand.",
        "History",
    )}
<div class="almanac-controls">
  <label class="almanac-select">
    <span>Period</span>
    <select data-summary-select aria-label="Select a month or season">
      <optgroup label="Months">{month_options}</optgroup>
      <optgroup label="Seasons">{season_options}</optgroup>
    </select>
  </label>
</div>
<div class="almanac-panels">{panels}</div>
<section class="content-section"><h2>Notes</h2><ul>{notes_items}</ul></section>
<script>
  (function () {{
    const select = document.querySelector('[data-summary-select]');
    const panels = Array.from(document.querySelectorAll('[data-summary-panel]'));
    if (!select) return;
    const render = () => {{
      const [kind, key] = String(select.value).split(':');
      panels.forEach(panel => {{
        panel.hidden = !(panel.dataset.summaryKind === kind && panel.dataset.summaryKey === key);
      }});
    }};
    select.addEventListener('change', render);
    render();
  }})();
</script>
"""

    record_cards = "".join(
        f"""
    <div class="record-card">
      <span class="record-label">{html.escape(record.label)}</span>
      <strong class="record-value">{record.value:g} {html.escape(record.unit)}</strong>
      <span class="record-date">{html.escape(record.on_date)}</span>
    </div>"""
        for record in almanac.all_time_records
    )
    month_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(period.name)}</td>
          <td>{_record_line(period.warmest_day)}</td>
          <td>{_record_line(period.coldest_day)}</td>
          <td>{_record_line(period.wettest_day)}</td>
          <td>{_record_line(period.windiest_day)}</td>
        </tr>"""
        for period in almanac.months
    )
    records_content = f"""{_page_intro(
        "All-Time Record Book",
        f"Debrecen's daily weather extremes across {almanac.total_days} ERA5 daily values from {coverage}.",
        "History",
    )}
<section class="content-section">
  <h2>All-Time Records</h2>
  <div class="record-grid">{record_cards}</div>
</section>
<section class="content-section">
  <h2>Extremes By Month</h2>
  <div class="table-scroll">
    <table>
      <thead><tr><th>Month</th><th>Warmest day</th><th>Coldest day</th><th>Wettest day</th><th>Windiest day</th></tr></thead>
      <tbody>{month_rows}</tbody>
    </table>
  </div>
</section>
<section class="content-section"><h2>Notes</h2><ul>{notes_items}</ul></section>
"""
    return summary_content, records_content


def build_site(
    config: AtlasConfig,
    period_start: str,
    period_end: str,
    daily_date: str,
    current_metrics: dict[str, float],
    daily_metrics: dict[str, float],
    baseline_metrics: dict[str, float],
    anomalies: list[Anomaly],
    climate_reference: ClimateReference,
    daily_climate_reference: ClimateReference,
    energy: EnergyIndex,
    daily_energy: EnergyIndex,
    electricity: ElectricitySummary,
    electricity_notes: list[str],
    profile: ModelProfile,
    station: StationObservations,
    radar: RadarArchive,
    lightning: LightningArchive,
    satellite: SatelliteArchive,
    fronts: FrontAnalysis,
    phenomena: PhenomenaAnalysis,
    analogs: AnalogAnalysis,
    synoptic: SynopticArchive,
    land: LandSurfaceAnalysis,
    physical_energy: PhysicalEnergy,
    daily_physical_energy: PhysicalEnergy,
    regime: RegimeClassification,
    daily_regime: RegimeClassification,
    almanac: Almanac,
    figure_paths: dict[str, Path],
    processed_paths: dict[str, Path],
    site_dir: Path | None = None,
    quality_notes: list[str] | None = None,
    edition_notice: str | None = None,
    verification: StationVerification | None = None,
    kinematics: StormKinematics | None = None,
    air_mass_origin: AirMassOrigin | None = None,
    radar_cells: RadarCellAnalysis | None = None,
    observational_coverage: list[InputCoverage] | None = None,
    withheld_notices: list[str] | None = None,
) -> Path:
    site_dir = site_dir or config.outputs.site_dir
    site_dir.mkdir(parents=True, exist_ok=True)

    # A withheld build leaves the previous edition serving with nothing to say a
    # newer one was attempted and rejected. The first edition that does publish
    # carries that history, so the gap in the record is legible on the page.
    if withheld_notices:
        withheld_text = " ".join(withheld_notices)
        edition_notice = (
            f"{edition_notice} {withheld_text}" if edition_notice else withheld_text
        )
    analysis_dir = site_dir / "analysis"
    if analysis_dir.exists():
        shutil.rmtree(analysis_dir)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    for stale in ["storms.html", "upper-air.html", "climate.html"]:
        stale_path = site_dir / stale
        if stale_path.exists():
            stale_path.unlink()
    public_figures = _copy_assets(figure_paths, site_dir)
    figures = {name: f"../{path}" for name, path in public_figures.items()}

    data_dir = site_dir / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    data_links: dict[str, str] = {}
    for name, source in processed_paths.items():
        target = data_dir / source.name
        shutil.copy2(source, target)
        data_links[name] = f"../data/{target.name}"
    activity_lens_source = processed_paths.get("activity_lenses")
    activity_lenses = _load_activity_lenses(
        activity_lens_source,
        daily_date,
        config.location.timezone,
    )
    activity_lens_href = (
        f"data/{activity_lens_source.name}" if activity_lens_source is not None else None
    )

    weather_story = build_weather_story(
        regime=regime,
        current_metrics=current_metrics,
        anomalies=anomalies,
        climate=climate_reference,
        fronts=fronts,
        phenomena=phenomena,
        profile=profile,
        land=land,
        physical_energy=physical_energy,
        lightning=lightning,
        radar=radar,
        lightning_radius_km=config.hungaromet.lightning_radius_km,
    )
    weather_story_payload = json_ready(asdict(weather_story))
    (data_dir / "weather_story.json").write_text(
        json.dumps(weather_story_payload, indent=2, allow_nan=False), encoding="utf-8"
    )
    data_links["weather_story"] = "../data/weather_story.json"

    almanac_payload = json_ready(asdict(almanac))
    (data_dir / "climate_almanac.json").write_text(
        json.dumps(almanac_payload, indent=2, allow_nan=False), encoding="utf-8"
    )
    data_links["climate_almanac"] = "../data/climate_almanac.json"

    if air_mass_origin is not None and air_mass_origin.available:
        (data_dir / "air_mass_origin.json").write_text(
            json.dumps(json_ready(asdict(air_mass_origin)), indent=2, allow_nan=False),
            encoding="utf-8",
        )
        data_links["air_mass_origin"] = "../data/air_mass_origin.json"

    location_label = f"{config.location.name}, {config.location.region}"
    share_payload = {
        "date": daily_date,
        "page_url": _report_url(config),
        "location": location_label,
        "kind_label": "Daily report",
        "regime_label": daily_regime.label,
        "regime_briefing": daily_regime.briefing,
        "temperature_c": daily_metrics.get("temperature_mean_c"),
        "precipitation_mm": daily_metrics.get("precipitation_total_mm"),
        "wind_ms": daily_metrics.get("wind_speed_mean_ms"),
        "cloud_pct": daily_metrics.get("cloud_cover_mean_pct"),
        "energy_label": daily_energy.label,
    }
    # The analysis pages cover the rolling 72-hour window, so they carry their own card
    # rather than reusing the single-day one.
    analysis_share_payload = {
        "date": f"{period_start} – {period_end}",
        "page_url": _analysis_url(config),
        "location": location_label,
        "kind_label": "72-hour analysis",
        "regime_label": regime.label,
        "regime_briefing": regime.briefing,
        "temperature_c": current_metrics.get("temperature_mean_c"),
        "precipitation_mm": current_metrics.get("precipitation_total_mm"),
        "wind_ms": current_metrics.get("wind_speed_mean_ms"),
        "cloud_pct": current_metrics.get("cloud_cover_mean_pct"),
        "energy_label": energy.label,
    }
    # After _copy_assets, which clears the assets directory before repopulating it.
    write_share_card(config, share_payload, site_dir)
    write_share_card(config, analysis_share_payload, site_dir, ANALYSIS_SHARE_CARD_ASSET)

    payload: dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
        "daily_date": daily_date,
        "current_metrics": current_metrics,
        "daily_metrics": daily_metrics,
        "baseline_metrics": baseline_metrics,
        "energy": asdict(energy),
        "daily_energy": asdict(daily_energy),
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
        "satellite": {
            "frames": satellite.frame_count,
            "products": {name: len(frames) for name, frames in satellite.frames.items()},
            "notes": satellite.notes,
        },
        "frontal_passages": [
            {**asdict(event), "time": event.time.isoformat()} for event in fronts.events
        ],
        "phenomena": [asdict(event) for event in phenomena.events],
        "historical_analogs": [asdict(match) for match in analogs.matches],
        "analog_notes": analogs.notes,
        "synoptic": {"frames": len(synoptic.times), "notes": synoptic.notes},
        "climatology": {
            "standard_period": (
                f"{config.climatology.standard_start_year}-"
                f"{config.climatology.standard_end_year}"
            ),
            "full_record_start_year": config.climatology.archive_start_year,
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
            "notes": physical_energy.notes,
        },
        "weather_story": weather_story_payload,
        "regime": asdict(regime),
        "daily_regime": asdict(daily_regime),
        "anomalies": [asdict(item) for item in anomalies],
        "quality_notes": quality_notes or [],
    }
    if activity_lenses is not None:
        payload["activity_lenses"] = activity_lenses
    (data_dir / "summary.json").write_text(
        json.dumps(json_ready(payload), indent=2, allow_nan=False), encoding="utf-8"
    )

    period_label = f"{config.location.name}, {config.location.region} - {period_start} to {period_end}"
    daily_label = f"{config.location.name}, {config.location.region} - {daily_date}"
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    station_coverage = next(
        (
            coverage
            for coverage in (observational_coverage or [])
            if coverage.name == "station"
        ),
        None,
    )
    publication_complete = (
        station_coverage.ok
        if station_coverage is not None
        else not station.frame.empty
    )

    observed_temp = float(pd.to_numeric(station.frame.get("temperature_c"), errors="coerce").mean()) if not station.frame.empty else float("nan")
    observed_rain = float(pd.to_numeric(station.frame.get("precipitation_mm"), errors="coerce").sum()) if not station.frame.empty else float("nan")
    observed_gust = float(pd.to_numeric(station.frame.get("wind_gust_ms"), errors="coerce").max()) if not station.frame.empty else float("nan")
    radar_max = float(radar.timeline["domain_max_dbz"].max()) if not radar.timeline.empty else float("nan")
    lightning_count = len(lightning.frame)
    # A failed archive and a genuinely quiet period both leave an empty frame. The
    # quiet reading is the comforting one, so it must never be printed by default.
    lightning_available = bool(getattr(lightning, "available", True))
    lightning_phrase = _lightning_phrase(lightning, lightning_count)
    closest_flash = float(lightning.frame["distance_km"].min()) if not lightning.frame.empty else float("nan")
    lightning_sentence = (
        f"{lightning_count:,} lightning events were inside the study radius; the closest was "
        f"{_fmt(closest_flash)} km from Debrecen."
        if lightning_available
        else "The LINET archive was unavailable for this period, so no strike count is "
        "reported. This is not a record of zero lightning."
    )
    best_analog = analogs.matches[0] if analogs.matches else None
    cape = profile.diagnostics.get("surface_based_cape_j_kg", float("nan"))
    pbl = profile.diagnostics.get("boundary_layer_height_m", float("nan"))
    target_day = pd.Timestamp(daily_date).date()

    def on_target_day(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty or "time" not in frame:
            return frame.iloc[0:0].copy()
        local_dates = pd.to_datetime(frame["time"], utc=True).dt.tz_convert(
            config.location.timezone
        ).dt.date
        return frame[local_dates == target_day].copy()

    daily_station = on_target_day(station.frame)
    daily_lightning = on_target_day(lightning.frame)
    daily_lightning_phrase = _lightning_phrase(lightning, len(daily_lightning))
    daily_radar = on_target_day(radar.timeline)
    daily_observed_temp = (
        float(pd.to_numeric(daily_station["temperature_c"], errors="coerce").mean())
        if not daily_station.empty
        else float("nan")
    )
    daily_observed_rain = (
        float(pd.to_numeric(daily_station["precipitation_mm"], errors="coerce").sum())
        if not daily_station.empty
        else float("nan")
    )
    daily_observed_gust = (
        float(pd.to_numeric(daily_station["wind_gust_ms"], errors="coerce").max())
        if not daily_station.empty
        else float("nan")
    )
    daily_radar_max = (
        float(pd.to_numeric(daily_radar["domain_max_dbz"], errors="coerce").max())
        if not daily_radar.empty
        else float("nan")
    )
    daily_events = [
        event
        for event in phenomena.events
        if event.start_time.tz_convert(config.location.timezone).date() <= target_day
        <= event.end_time.tz_convert(config.location.timezone).date()
    ]

    def phenomenon_items(events: list[WeatherPhenomenon], empty_text: str) -> str:
        if not events:
            return (
                '<li><div class="event-time">Entire period</div><div class="event-copy">'
                f'<strong>{html.escape(empty_text)}</strong><p>No objective threshold was met.</p></div></li>'
            )
        items = []
        for event in events:
            start = event.start_time.tz_convert(config.location.timezone)
            end = event.end_time.tz_convert(config.location.timezone)
            items.append(
                f'<li><div class="event-time">{start.strftime("%d %b %H:%M")} - {end.strftime("%H:%M %Z")}</div>'
                f'<div class="event-copy"><strong>{html.escape(event.kind)}</strong><p>{html.escape(event.evidence)}</p>'
                f'<div class="evidence-meta">{_evidence_badge("derived")} '
                f'{event.confidence:.0%} confidence &middot; {html.escape(event.source)}</div></div></li>'
            )
        return "".join(items)

    day_regime_label = daily_regime.label.replace(" period", " day")
    day_briefing = daily_regime.briefing.replace(daily_regime.label, day_regime_label, 1).replace(
        "period solar radiation", "daily solar radiation"
    )
    home = f"""
<header class="home-intro">
  <div class="eyebrow">Debrecen meteorological record</div>
  <h1>{html.escape(config.project.name)}</h1>
  <p class="home-question">What kind of weather did Debrecen just have, how unusual was it, and what did it imply for solar and wind energy potential?</p>
  <p class="home-summary">Atlas is a deterministic weather diary for Debrecen. It combines airport observations, remote sensing, gridded climate records, atmospheric diagnostics, historical analogs and physically based renewable-energy estimates in two regularly updated publications.</p>
</header>
<section aria-labelledby="current-publications">
  <div class="section-heading"><h2 id="current-publications">Current publications</h2></div>
  <div class="publication-ledger">
    <a class="publication-row" href="report.html">
      <span class="publication-kind">Daily public</span>
      <div class="publication-copy"><h2>Daily Public Report</h2><p>The last complete local day, with a concise weather account, objective events, renewable yield and climate context.</p></div>
      <div class="publication-date">Latest edition<strong>{html.escape(daily_date)} &rarr;</strong></div>
    </a>
    <a class="publication-row" href="analysis/index.html">
      <span class="publication-kind">72-hour expert</span>
      <div class="publication-copy"><h2>Meteorological Analysis</h2><p>Surface, synoptic, satellite, radar, upper-air, land-surface, climate and energy diagnostics for the latest complete period.</p></div>
      <div class="publication-date">Current window<strong>{html.escape(period_start)} to {html.escape(period_end)} &rarr;</strong></div>
    </a>
    <a class="publication-row" href="archive/index.html">
      <span class="publication-kind">Preserved record</span>
      <div class="publication-copy"><h2>Report Archive</h2><p>One search across saved reports, rolling analyses and their de-duplicated objective weather-event evidence.</p></div>
      <div class="publication-date">Browse history<strong>Open archive &rarr;</strong></div>
    </a>
  </div>
</section>
<section class="content-section">
  <h2>Evidence, not decoration</h2>
  <p class="home-section-lead">The report begins with what was observed and labels every gridded, remotely sensed or model-derived contribution. Interactive figures support inspection, while deterministic text records the thresholds and evidence behind each interpretation.</p>
  <div class="source-key" aria-label="Atlas evidence sources">
    <span class="source-chip">{_evidence_badge("observed")} HungaroMet Debrecen Airport</span>
    <span class="source-chip">{_evidence_badge("remote")} Radar + LINET + Meteosat</span>
    <span class="source-chip">{_evidence_badge("model")} Open-Meteo + ERA5</span>
    <span class="source-chip">{_evidence_badge("derived")} Column diagnostics + renewable yield</span>
  </div>
  <div class="home-definition">
    <div><span>Geographic scope</span><strong>Debrecen, Hungary</strong></div>
    <div><span>Climate reference</span><strong>1991-2020 standard normal, recent decade and full record</strong></div>
    <div><span>Publication cadence</span><strong>Daily public record and rolling 72-hour analysis</strong></div>
  </div>
</section>
<div class="methods-grid">
  <section class="content-section"><h2>Scientific frame</h2><p>Atlas is descriptive, diagnostic, climatological and energy-oriented. It is not forecast calibration, an operational warning service or a plant-level production forecast.</p></section>
  <section class="content-section"><h2>Open data</h2><p>The pipeline uses public HungaroMet, Open-Meteo and Energy-Charts endpoints without repository secrets. Optional-source failures remain explicitly unavailable rather than becoming false zeroes.</p></section>
</div>
<section class="content-section"><h2>Project notes</h2><p class="home-section-lead">Methods, source provenance and implementation details are maintained in the <a href="https://github.com/danebencedavid/Atlas">Atlas repository</a>. Every analytical page includes its own evidence notes and machine-readable downloads.</p></section>
"""
    public_overview = f"""
<header class="hero">
  <div>
    <div class="eyebrow">Daily public report | {html.escape(daily_label)}</div>
    <h1>{html.escape(config.project.name)}</h1>
    <p class="hero-regime">{html.escape(day_regime_label)}</p>
    <p class="brief">{html.escape(day_briefing)}</p>
    <p class="meta">A concise account of the last complete day in Debrecen.</p>
    <div class="source-key" aria-label="Daily report evidence">
      <span class="source-chip">{_evidence_badge("observed")} Debrecen Airport</span>
      <span class="source-chip">{_evidence_badge("model")} Open-Meteo</span>
      <span class="source-chip">{_evidence_badge("remote")} Radar + lightning</span>
      <span class="source-chip">{_evidence_badge("derived")} Renewable yield</span>
    </div>
  </div>
  <div class="summary" aria-label="Daily renewable weather summary">
    <div class="score"><span>PV yield</span><strong>{_fmt(daily_physical_energy.pv_yield_kwh_per_kwp, 1)}</strong><span>kWh per installed kWp</span></div>
    <div class="score"><span>Wind full-load hours</span><strong>{_fmt(daily_physical_energy.wind_full_load_hours, 1)}</strong><span>generic 100 m turbine</span></div>
    <div class="score"><span>Weather score</span><strong>{_fmt(daily_energy.combined_score, 0)}</strong><span>{html.escape(daily_energy.label)}</span></div>
  </div>
</header>
<div class="public-facts"><div><span>Airport mean</span><strong>{_fmt(daily_observed_temp)} C</strong></div><div><span>Airport precipitation</span><strong>{_fmt(daily_observed_rain)} mm</strong></div><div><span>Peak airport gust</span><strong>{_fmt(daily_observed_gust)} m/s</strong></div></div>
"""
    public_overview += _activity_lenses_section(
        activity_lenses,
        activity_lens_href,
    )
    public_overview += _plot_section(
        "Yesterday Hour By Hour",
        public_figures["daily_meteogram"],
        "Daily Debrecen meteogram",
        "Read downward through temperature and dew point, pressure, wind and gusts, precipitation, then cloud and solar radiation.",
        "meteogram",
    )
    public_overview += f'<p class="public-lead">{_evidence_badge("derived")}<strong>Deterministic interpretation.</strong> Yesterday was classified as {html.escape(day_regime_label.lower())}. Atlas detected {_phenomena_phrase(phenomena)}, {daily_lightning_phrase} within {config.hungaromet.lightning_radius_km:.0f} km, and {_radar_peak_phrase(radar, daily_radar_max)}.</p>'

    public_weather = _page_intro(
        "Yesterday's Weather",
        "The observed day at Debrecen Airport with gridded context used where continuous station data is unavailable.",
        daily_label,
    )
    public_weather += f'<p class="analysis-lead">{_evidence_badge("observed")}<strong>Observed at the airport.</strong> Mean {_fmt(daily_observed_temp)} C, {_fmt(daily_observed_rain)} mm precipitation and a peak gust of {_fmt(daily_observed_gust)} m/s.</p>'
    public_weather += _plot_section("Daily Meteogram", public_figures["daily_meteogram"], "Daily weather timeline", "Hover or zoom to inspect the timing of temperature, pressure, wind, rain, cloud and sunshine.", "meteogram")

    public_events = _page_intro(
        "Weather Events",
        "Objective events detected during the last complete day, with evidence and data source shown explicitly.",
        daily_label,
    )
    public_events += f'<section class="content-section"><h2>Daily chronology</h2><ul class="event-list">{phenomenon_items(daily_events, "No notable event detected")}</ul></section>'

    public_energy = _page_intro(
        "Renewable Weather",
        "Reference-system PV and wind yield implied by yesterday's Debrecen weather.",
        daily_label,
    )
    public_energy += f'<div class="metric-band"><div class="metric"><span>PV weather yield</span><strong>{_fmt(daily_physical_energy.pv_yield_kwh_per_kwp, 1)}</strong><span>kWh/kWp</span></div><div class="metric"><span>PV capacity factor</span><strong>{_fmt(daily_physical_energy.pv_capacity_factor_pct, 1)}</strong><span>percent</span></div><div class="metric"><span>Wind full-load hours</span><strong>{_fmt(daily_physical_energy.wind_full_load_hours, 1)}</strong><span>hours</span></div><div class="metric"><span>Wind capacity factor</span><strong>{_fmt(daily_physical_energy.wind_capacity_factor_pct, 1)}</strong><span>percent</span></div></div>'
    public_energy += _plot_section("Daily PV And Wind Yield", public_figures["daily_physical_energy"], "Daily physical renewable yield", "PV is a fixed reference array and wind is a generic 100 m turbine; neither is a plant forecast.", "physical-energy")

    public_context = _page_intro(
        "Climate Context",
        "Yesterday placed within the recent week, the 1991-2020 standard normal, the recent decade and the full ERA5 record.",
        daily_label,
    )
    public_context += _plot_section("Seven-Day Weather Diary", public_figures["seven_day_context"], "Seven-day weather context", "The highlighted final period is the active 72-hour expert analysis; the latest day is the public report.", "context")
    public_context += _plot_section("How Unusual Was Yesterday?", public_figures["daily_climate_reference"], "Daily climate reference comparison", "The upper panel compares standardized anomalies against 1991-2020 and the recent decade. The lower panel ranks yesterday across the full ERA5 record.", "climate-reference")

    public_methods = _page_intro(
        "About This Report",
        "What is observed, what is model-derived, and when the daily publication updates.",
        daily_label,
    )
    public_methods += f"""
<div class="methods-grid"><section class="content-section"><h2>Publication</h2><p>The public report is rebuilt daily from the last complete Europe/Budapest calendar day. It uses the same deterministic calculations as the meteorological analysis, with shorter explanations and fewer diagnostics.</p></section>
<section class="content-section"><h2>Evidence</h2><p>HungaroMet station, radar, LINET and Meteosat products are observational or remotely sensed. Open-Meteo supplies continuous gridded surface fields, model pressure levels and ERA5 climate fields. Optional-source failures are reported as unavailable, never treated as observed zeroes.</p></section></div>
<section class="content-section"><h2>Climate references</h2><p>"Normal" means the 1991-2020 ERA5 standard reference. The recent-decade comparison and full-record percentile are shown separately.</p></section>
"""

    analysis_overview = f"""
<header class="hero">
  <div>
    <div class="eyebrow">{html.escape(period_label)}</div>
    <h1>{html.escape(config.project.name)}</h1>
    <p class="hero-regime">{html.escape(regime.label)}</p>
    <p class="brief">{html.escape(regime.briefing)}</p>
    <p class="meta">{html.escape(config.project.tagline)}</p>
    <div class="source-key" aria-label="Analysis evidence">
      <span class="source-chip">{_evidence_badge("observed")} Station 64711</span>
      <span class="source-chip">{_evidence_badge("remote")} Radar + LINET + MSG</span>
      <span class="source-chip">{_evidence_badge("model")} ERA5 + model levels</span>
      <span class="source-chip">{_evidence_badge("derived")} Energy + diagnostics</span>
    </div>
  </div>
  <div class="summary" aria-label="Renewable weather scores">
    <div class="score"><span>PV yield</span><strong>{_fmt(physical_energy.pv_yield_kwh_per_kwp, 1)}</strong><span>kWh per installed kWp</span></div>
    <div class="score"><span>Wind full-load hours</span><strong>{_fmt(physical_energy.wind_full_load_hours, 1)}</strong><span>generic 100 m turbine</span></div>
    <div class="score"><span>Combined weather score</span><strong>{_fmt(energy.combined_score, 0)}</strong><span>{html.escape(energy.label)}</span></div>
  </div>
</header>
"""
    analysis_overview += _plot_section(
        "Annotated 72-Hour Meteogram",
        figures["meteogram"],
        "Interactive rolling three-day meteogram with frontal annotations",
        "Read downward through temperature and dew point, pressure, wind and gusts, precipitation, then cloud and radiation. Red vertical markers identify objective frontal-passage candidates.",
        "meteogram",
    )
    analysis_overview += f"""
<p class="analysis-lead">{_evidence_badge("derived")}<strong>Deterministic interpretation.</strong> {html.escape(regime.briefing)} Atlas found {_front_phrase(fronts)}, {lightning_phrase} within {config.hungaromet.lightning_radius_km:.0f} km, and a maximum sampled radar reflectivity of {_fmt(radar_max)} dBZ.</p>
<div class="insight-grid">
  <article class="insight">{_evidence_badge("observed")}<h3>Debrecen Airport</h3><p>Mean {_fmt(observed_temp)} C, {_fmt(observed_rain)} mm precipitation and a peak gust of {_fmt(observed_gust)} m/s from station {station.station_id}.</p></article>
  <article class="insight">{_evidence_badge("remote")}<h3>Storm character</h3><p>{lightning_sentence}</p></article>
  <article class="insight">{_evidence_badge("model")}<h3>Atmospheric column</h3><p>Selected-profile surface-based CAPE was {_fmt(cape, 0)} J/kg and boundary-layer height was {_fmt(pbl, 0)} m.</p></article>
  <article class="insight">{_evidence_badge("derived")}<h3>Historical likeness</h3><p>{html.escape(best_analog.start_date + ' to ' + best_analog.end_date + ': ' + best_analog.character) if best_analog else 'No robust seasonal analog was available.'}</p></article>
</div>
"""

    story_page = _page_intro(
        "Weather Story",
        weather_story.briefing,
        period_label,
    )
    story_page += _weather_story_graph(weather_story)

    weather = _page_intro(
        "Surface And Synoptic Analysis",
        "Observed conditions at Debrecen Airport, their relationship to the gridded record, and the synoptic environment in which the period evolved.",
        period_label,
    )
    weather += f'<p class="analysis-lead">{_evidence_badge("observed")}<strong>Observation first.</strong> Station {station.station_id} recorded a mean temperature of {_fmt(observed_temp)} C, {_fmt(observed_rain)} mm of precipitation and a maximum gust of {_fmt(observed_gust)} m/s. Dotted lines in the comparison are gridded context, not observations.</p>'
    weather += _plot_section(
        "Debrecen Airport Observation Ledger",
        figures["station_comparison"],
        "HungaroMet station observations compared with gridded weather",
        "Solid traces are HungaroMet 10-minute station observations aggregated hourly. Dotted traces are the gridded series used for climatological continuity; differences expose representativeness and model-analysis error.",
        "electricity",
        "Observed at HungaroMet station 64711, Debrecen Airport.",
    )
    weather += _plot_section(
        "Selectable Synoptic Dynamics",
        figures["synoptic_evolution"],
        "Animated Central European synoptic analysis",
        "Select air-mass, 300 hPa jet, 500 hPa vorticity, 700 hPa moisture/ascent, or 850 hPa theta-e/frontogenesis mode, then animate the shared timeline.",
        "synoptic",
    )
    weather += _plot_section("Wind Regime", figures["wind_rose"], "Interactive wind rose", "Spokes point toward the direction the wind came from. Length is frequency and color separates speed classes.", "context")
    weather += _plot_section("Pressure And Frontal Tendency", figures["pressure_tendency"], "Interactive pressure tendency", "Six-hour pressure changes expose troughs, frontal passages and the establishment or breakdown of anticyclonic conditions.", "context")
    air_mass_source_note = (
        f"Open-Meteo {config.trajectory.level_hpa} hPa winds on a "
        f"{config.trajectory.grid_step_degrees:g}-degree grid; a kinematic single-level trajectory, "
        "not a vertically resolved parcel history."
    )
    weather += _plot_section(
        "Air-Mass Back-Trajectory",
        figures["air_mass_trajectory"],
        "Back-trajectory map of the arriving air mass",
        "The path traces where the air over Debrecen had been. Colour runs from arrival back through time, and hovering gives the position, distance and temperature at each hour.",
        "context",
        air_mass_source_note,
    )
    weather += _air_mass_origin_section(air_mass_origin)

    storms = _page_intro("Storms And Satellite", "A synchronized Meteosat, radar, lightning and objective-phenomena reconstruction of the complete 72-hour period.", period_label)
    storms += f'<p class="analysis-lead">{_evidence_badge("derived")}<strong>Event diagnosis.</strong> Radar reported {_radar_peak_phrase(radar, radar_max)} in the sampled domain. LINET reported {lightning_phrase} within {config.hungaromet.lightning_radius_km:.0f} km, and Atlas identified {_phenomena_phrase(phenomena)}.</p>'
    storms += _plot_section("Meteosat, Radar And Lightning Diary", figures["satellite_diary"], "Synchronized Meteosat satellite diary", "Choose Airmass, Natural Colour, Night Microphysics, Fog RGB or InfraCloud; play the frames while the cursor follows the nearest radar and lightning observations.", "satellite", "HungaroMet MSG imagery sampled every three hours for a practical self-contained archive.")
    storms += _plot_section("Objective Phenomena Strip", figures["phenomena_timeline"], "Objective weather phenomena chronology", "Each segment is a threshold-based candidate. Hover to inspect evidence, confidence and provenance.", "phenomena")
    storms += f'<section class="content-section"><h2>Evidence ledger</h2><ul class="event-list">{phenomenon_items(phenomena.events, "No objective phenomenon detected")}</ul></section>'
    storms += _plot_section("Radar Replay And Accumulation", figures["radar_archive"], "Animated radar replay and accumulation proxy", "Play the sampled reflectivity sequence on the left. The right panel integrates a standard Z-R conversion and is an approximate spatial precipitation proxy, not a gauge-adjusted accumulation product.", "radar")
    storms += _radar_cells_section(radar_cells)
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
    upper_air += f'<p class="analysis-lead">{_evidence_badge("model")}<strong>Selected profile.</strong> CAPE {_fmt(cape, 0)} J/kg, precipitable water {_fmt(profile.diagnostics.get("precipitable_water_mm", float("nan")), 0)} mm and wet-bulb-zero height {_fmt(profile.diagnostics.get("wet_bulb_zero_m_asl", float("nan")), 0)} m ASL.</p><div class="diagnostic-ledger">{ledger}</div>'
    upper_air += _plot_section("Model Skew-T", figures["model_profile"], "Interactive Skew-T-style model atmospheric profile", "Temperature, dew point and wind are plotted on pressure surfaces. The ledger adds parcel-derived CAPE, CIN, LCL, LFC, equilibrium level and precipitable water where calculable.", "profile", profile_note)
    upper_air += _plot_section("Hodograph", figures["hodograph"], "Interactive hodograph and bulk wind shear", "The curve traces horizontal wind components with height. Length shows speed shear, curvature shows directional turning, and the inset reports layer bulk shear.", "hodograph", profile_note)
    upper_air += _storm_kinematics_section(kinematics)
    upper_air += _plot_section("Parcel And Boundary-Layer Evolution", figures["column_diagnostics"], "Parcel and boundary-layer time series", "CAPE and CIN show buoyancy, PBL height shows mixing depth, total-column water tracks moisture availability, and freezing-level evolution constrains precipitation phase and hail melting.", "physical-energy", profile_note)
    upper_air += _plot_section("Time-Pressure Curtain", figures["time_pressure"], "Interactive time-pressure atmospheric curtain", "Time runs left to right and pressure decreases upward. Switch among humidity, temperature anomaly and wind speed to diagnose layer evolution and frontal depth.", "time-pressure", "A Debrecen time-pressure diagnostic adapted from a Hovmoller layout.")

    analog_rows = "".join(
        f'<div class="analog-row"><strong>{html.escape(match.start_date)} to {html.escape(match.end_date)}</strong><span>{match.similarity:.0f}% similarity</span><div>{html.escape(match.character)}; {_fmt(match.metrics.get("temperature_mean_c", float("nan")))} C, {_fmt(match.metrics.get("precipitation_total_mm", float("nan")))} mm and {_fmt(match.metrics.get("wind_speed_10m_mean_ms", float("nan")))} m/s mean 10 m wind.</div></div>'
        for match in analogs.matches
    ) or '<p>No robust historical analogs were available.</p>'
    climate = _page_intro("Debrecen Climate And Analogs", "The current period compared with the 1991-2020 standard normal, the recent decade, the full ERA5 record and closest seasonal analogs.", period_label)
    climate += _plot_section("Standard Normal, Recent Decade And Full Record", figures["climate_reference"], "Climatological reference comparison", "Compare standardized anomalies against 1991-2020 and the recent decade, then inspect the empirical percentile across the full ERA5 record.", "climate-reference")
    climate += f'<p class="analysis-lead">{_evidence_badge("derived")}<strong>Historical likeness.</strong> {html.escape(best_analog.start_date + " to " + best_analog.end_date) + " was the closest match, described as " + html.escape(best_analog.character) + "." if best_analog else "No robust analog could be selected."}</p><section class="content-section"><h2>Closest seasonal analogs</h2><div class="analog-list">{analog_rows}</div></section>'
    climate += _plot_section("Seven-Day Weather Diary", figures["seven_day_context"], "Seven-day weather context", "The highlighted final three days are the active report; the preceding four days preserve the transition into the current regime.", "context")
    climate += _plot_section("Anomaly Structure", figures["anomaly_bars"], "Weather anomaly bars", "Bars show standard deviations from the same calendar window in prior years. Sign means above or below normal, not favorable or unfavorable.")
    climate += _plot_section("Daily Regime Evolution", figures["regime_strip"], "Daily regime strip", "Each segment is one local day classified with transparent weather rules.", "compact")
    climate += _plot_section("Solar Climatology", figures["solar_diurnal"], "Solar diurnal curves", "Daily radiation profiles are compared with the historical median to distinguish clear, overcast and intermittently cloudy solar regimes.")

    electricity_page = _page_intro("Land Surface And Energy", "Ninety-day soil and atmospheric water balance followed by physical renewable yields and Hungary-wide electricity-system context.", period_label)
    electricity_page += f'<p class="analysis-lead">{_evidence_badge("model")}<strong>{html.escape(land.moisture_context)}.</strong> The 90-day precipitation-minus-ET0 balance was {_fmt(land.metrics.get("water_balance_90d_mm", float("nan")))} mm, at the {_fmt(land.water_balance_percentiles.get(90, float("nan")), 0)}th percentile of 1991-2020.</p>'
    electricity_page += _plot_section("Land Surface And Water Balance", figures["land_surface"], "Soil, VPD, ET0 and water-balance analysis", "Read soil temperature and moisture by depth, atmospheric vapour-pressure deficit, ET0, and daily/cumulative precipitation minus ET0 across the preceding 90 days.", "land-surface", "Open-Meteo best-match gridded land fields; the 1991-2020 reference is fixed ERA5, and water balance excludes runoff and irrigation.")
    electricity_page += f'<p class="analysis-lead">{_evidence_badge("derived")}<strong>Weather translated into production.</strong> A fixed south-facing reference array produced an estimated {_fmt(physical_energy.pv_yield_kwh_per_kwp, 1)} kWh/kWp. A generic 100 m turbine produced {_fmt(physical_energy.wind_full_load_hours, 1)} full-load hours at a mean capacity factor of {_fmt(physical_energy.wind_capacity_factor_pct, 1)}%.</p><div class="metric-band" aria-label="Physical and system energy summary"><div class="metric"><span>PV weather yield</span><strong>{_fmt(physical_energy.pv_yield_kwh_per_kwp, 1)}</strong><span>kWh/kWp</span></div><div class="metric"><span>Wind capacity factor</span><strong>{_fmt(physical_energy.wind_capacity_factor_pct, 1)}</strong><span>percent</span></div><div class="metric"><span>Hungary average load</span><strong>{_fmt_grouped(electricity.average_load_mw)}</strong><span>MW</span></div><div class="metric"><span>Day-ahead price</span><strong>{_fmt(electricity.average_price_eur_mwh, 0)}</strong><span>EUR/MWh</span></div></div>'
    electricity_page += _plot_section("Physical PV And Wind Yield", figures["physical_energy"], "Physically based renewable weather yield", "PV uses solar position, plane-of-array irradiance and cell-temperature derating. Wind uses 100 m speed, moist-air density and a generic turbine power curve.", "physical-energy")
    electricity_page += _plot_section("Hungary Electricity Context", figures["electricity_overview"], "Hungary electricity system overview", "Compare national load, residual load, generation and price with the local Debrecen weather chronology.", "electricity", "Energy-Charts and ENTSO-E are Hungary-wide context, not Debrecen metering.")
    electricity_page += _plot_section("Weather-Electricity Relationships", figures["weather_electricity_links"], "Weather and electricity relationships", "Hourly associations are diagnostic and do not establish causality or represent a plant-level power forecast.", "relationships")

    standard_lookup = {item.metric: item for item in climate_reference.standard_anomalies}
    recent_lookup = {item.metric: item for item in climate_reference.recent_anomalies}
    anomalies_rows = "\n".join(
        f"<tr><th>{html.escape(standard_lookup[metric].label)}</th><td>{_fmt(standard_lookup[metric].value)}</td>"
        f"<td>{_fmt(standard_lookup[metric].baseline_mean)} ({standard_lookup[metric].anomaly:+.1f})</td>"
        f"<td>{_fmt(recent_lookup[metric].baseline_mean)} ({recent_lookup[metric].anomaly:+.1f})</td>"
        f"<td>{_fmt(climate_reference.full_record_percentiles[metric], 0)}th</td></tr>"
        for metric in standard_lookup
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
            + satellite.notes
            + fronts.notes
            + phenomena.notes
            + analogs.notes
            + synoptic.notes
            + climate_reference.notes
            + land.notes
            + physical_energy.notes
        )
    )
    baseline_period = processed_paths.get("baseline_metrics", Path("baseline_metrics.csv")).name
    downloads = [
        ("Current weather observations", data_links.get("current_hourly")),
        ("Seven-day weather context", data_links.get("seven_day_context_hourly")),
        ("Period metrics", data_links.get("period_metrics")),
        ("Baseline metrics", data_links.get("baseline_metrics")),
        ("1991-2020 standard-normal metrics", data_links.get("standard_normal_metrics")),
        ("Full-record climate metrics", data_links.get("full_record_metrics")),
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
        ("Objective phenomena ledger", data_links.get("phenomena")),
        ("Historical analogs", data_links.get("historical_analogs")),
        ("Synoptic analysis fields", data_links.get("synoptic_fields")),
        ("Physical PV and wind yields", data_links.get("physical_energy")),
        ("Weather story graph", data_links.get("weather_story")),
        ("Air-mass back-trajectory", data_links.get("air_mass_origin")),
        ("Climate almanac", data_links.get("climate_almanac")),
        ("Land-surface hourly context", data_links.get("land_surface_hourly")),
        ("Land-surface daily context", data_links.get("land_surface_daily")),
        ("Machine-readable summary", "../data/summary.json"),
        ("Month, season and record-book climate almanac", data_links.get("climate_almanac")),
    ]
    available_downloads = [(label, str(path)) for label, path in downloads if path]
    download_items = "\n".join(
        '<li><a href="{path}" download>'
        '<span class="download-filemark" aria-hidden="true">&#8595;</span>'
        '<span class="download-copy"><strong>{label}</strong><small>{file_type} data</small></span>'
        '<span class="download-action">Download</span></a></li>'.format(
            path=html.escape(path),
            label=html.escape(label),
            file_type=html.escape(Path(path.split("?", 1)[0]).suffix.lstrip(".").upper() or "DATA"),
        )
        for label, path in available_downloads
    )
    methods = _page_intro(
        "Methods And Data",
        "Transparent baselines, explainable regime rules, source notes, and downloadable outputs for the current report.",
        period_label,
    )
    methods += f"""
<section class="content-section">
  <h2>Climatological Reference Ledger</h2>
  <div class="table-scroll">
    <table>
      <thead><tr><th>Metric</th><th>This period</th><th>1991-2020 mean (anomaly)</th><th>Recent 10-year mean (anomaly)</th><th>{config.climatology.archive_start_year}-present percentile</th></tr></thead>
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
    <p>HungaroMet supplies Debrecen Airport observations, composite radar, LINET lightning and Meteosat imagery. Open-Meteo supplies the continuous gridded surface record, pressure-level model fields, synoptic grid, the wide-domain {config.trajectory.level_hpa} hPa wind field the back-trajectory integrates through, land fields and ERA5 climate archive. Standard normals use 1991-2020; the recent comparison retains the prior {config.baseline.years} years and is stored in {html.escape(baseline_period)}.</p>
    <ul>{quality_items}</ul>
    <ul>{electricity_note_items}</ul>
    <ul>{profile_note_items}</ul>
    <ul>{expert_note_items}</ul>
  </section>
</div>
{_observational_coverage_section(observational_coverage)}
{_verification_section(verification)}
<section class="content-section downloads-section">
  <div class="downloads-heading"><div><h2>Data Downloads</h2><p>Generated evidence files for independent inspection and reuse.</p></div><span class="download-count">{len(available_downloads)} files</span></div>
  <ul class="download-list">{download_items}</ul>
</section>
"""

    (site_dir / "index.html").write_text(
        _page_document(
            config,
            "index.html",
            "Project Overview",
            "Atlas is a daily and rolling 72-hour meteorological record for Debrecen.",
            home,
            updated,
            "home",
            edition_notice,
            None,
        ),
        encoding="utf-8",
    )

    public_documents = {
        "report.html": ("Daily Overview", "Daily public weather report for Debrecen.", public_overview),
        "weather.html": ("Daily Weather", "Yesterday's observed weather in Debrecen.", public_weather),
        "events.html": ("Daily Events", "Objective weather events detected around Debrecen yesterday.", public_events),
        "energy.html": ("Daily Energy", "Daily PV and wind weather yield for Debrecen.", public_energy),
        "context.html": ("Climate Context", "Daily Debrecen weather in weekly and climatological context.", public_context),
        "methods.html": ("About", "Methods and evidence for the Atlas public report.", public_methods),
    }
    for filename, (page_name, description, content) in public_documents.items():
        target = site_dir / filename
        target.write_text(
            _page_document(
                config,
                filename,
                page_name,
                description,
                content,
                updated,
                "public",
                edition_notice,
                share_payload,
                daily_date,
                publication_complete,
            ),
            encoding="utf-8",
        )

    analysis_documents = {
        "index.html": ("Analysis Overview", "Rolling 72-hour Debrecen meteorological analysis.", analysis_overview),
        "story.html": ("Weather Story", "Evidence-linked weather story for the rolling Debrecen analysis.", story_page),
        "surface-synoptic.html": ("Surface & Synoptic", "Observed surface weather and selectable synoptic dynamics.", weather),
        "storms-satellite.html": ("Storms & Satellite", "Meteosat, radar, lightning and objective phenomena.", storms),
        "upper-air.html": ("Upper Air & Dynamics", "Parcel, boundary-layer and atmospheric-profile diagnostics.", upper_air),
        "climate.html": ("Climate & Analogs", "Standard normals, full-record ranks and historical analogs.", climate),
        "land-energy.html": ("Land Surface & Energy", "Land water balance, renewable yield and electricity context.", electricity_page),
        "methods.html": ("Methods & Evidence", "Atlas methods, source quality and data downloads.", methods),
    }
    for filename, (page_name, description, content) in analysis_documents.items():
        target = analysis_dir / filename
        target.write_text(
            _page_document(
                config,
                filename,
                page_name,
                description,
                content,
                updated,
                "analysis",
                edition_notice,
                analysis_share_payload,
                f"{period_start} to {period_end}",
                publication_complete,
            ),
            encoding="utf-8",
        )

    summary_content, records_content = _almanac_pages(config, almanac)
    (site_dir / "summary.html").write_text(
        _page_document(
            config,
            "summary.html",
            "Season & Month Summary",
            "Select a calendar month or meteorological season for a Debrecen climate digest built from the full ERA5 daily archive.",
            summary_content,
            updated,
            "summary",
            edition_notice,
            None,
        ),
        encoding="utf-8",
    )
    (site_dir / "records.html").write_text(
        _page_document(
            config,
            "records.html",
            "All-Time Record Book",
            "Debrecen's warmest, coldest, wettest, windiest and other daily extremes across the full ERA5 archive.",
            records_content,
            updated,
            "records",
            edition_notice,
            None,
        ),
        encoding="utf-8",
    )

    return site_dir / "index.html"
