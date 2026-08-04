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
from atlas.climatology import ClimateReference
from atlas.config import AtlasConfig
from atlas.electricity import ElectricitySummary
from atlas.energy import EnergyIndex, PhysicalEnergy
from atlas.fronts import FrontAnalysis
from atlas.hungaromet import LightningArchive, RadarArchive, StationObservations
from atlas.land import LandSurfaceAnalysis
from atlas.phenomena import PhenomenaAnalysis, WeatherPhenomenon
from atlas.profile import ModelProfile
from atlas.regimes import RegimeClassification
from atlas.satellite import SatelliteArchive
from atlas.serialization import json_ready
from atlas.synoptic import SynopticArchive


PUBLIC_PAGES = (
    ("index.html", "Overview"),
    ("weather.html", "Weather"),
    ("events.html", "Events"),
    ("energy.html", "Energy"),
    ("context.html", "Climate Context"),
    ("methods.html", "Methods"),
)

ANALYSIS_PAGES = (
    ("index.html", "Overview"),
    ("surface-synoptic.html", "Surface & Synoptic"),
    ("storms-satellite.html", "Storms & Satellite"),
    ("upper-air.html", "Upper Air & Dynamics"),
    ("climate.html", "Climate & Analogs"),
    ("land-energy.html", "Land Surface & Energy"),
    ("methods.html", "Methods & Evidence"),
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
.viz-frame.satellite { height: 860px; }
.viz-frame.land-surface { height: 940px; }
.viz-frame.climate-reference { height: 800px; }
.viz-frame.phenomena { height: 560px; }
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
  .viz-frame.satellite, .viz-frame.land-surface { height: 820px; }
  .help-panel { left: auto; right: -8px; }
}
"""


DATA_FIRST_CSS = """
:root {
  --ink: #232323;
  --ink-soft: #50504d;
  --muted: #7b7a77;
  --line: #e7e7e3;
  --line-strong: #d8d8d3;
  --paper: #ffffff;
  --panel: #ffffff;
  --canvas: #ffffff;
  --rail: #f6f6f4;
  --hover: #ebebe8;
  --selected: #e7e7e3;
  --blue: #3f72a4;
  --blue-soft: #eaf1f7;
  --green: #43816b;
  --gold: #b47a27;
  --red: #cf5146;
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
.sidebar-note {
  margin: auto 4px 2px;
  padding: 10px;
  color: var(--muted);
  background: rgba(255,255,255,.55);
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  font-size: 10px;
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
.hero {
  min-height: 0;
  display: block;
  padding: 0 0 12px;
}
.eyebrow {
  margin-bottom: 7px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
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
.meta { margin: 9px 0 0; font-size: 10px; }
.source-key {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 14px 0 3px;
}
.source-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 7px;
  color: var(--ink-soft);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 10px;
}
.source-chip b {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 9px;
}
.source-chip.observed b { color: var(--green); }
.source-chip.gridded b { color: var(--blue); }
.source-chip.remote b { color: var(--gold); }
.source-chip.derived b { color: var(--red); }
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
.plot-section:first-of-type { margin-top: 24px; }
.section-heading { align-items: flex-start; margin-bottom: 14px; }
.section-heading::before {
  flex: 0 0 auto;
  padding-top: 5px;
  color: #93928e;
  content: "DATA";
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 9px;
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
  font-size: 9px;
  text-transform: uppercase;
}
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
  font-size: 9px;
}
.insight p, .event-copy p { color: var(--ink-soft); font-size: 12px; }
.event-list, .analog-list { border-top-color: var(--line-strong); }
table { font-size: 12px; }
th, td { border-color: var(--line); }
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
  font-size: 10px;
}
@media (max-width: 980px) and (min-width: 721px) {
  :root { --sidebar: 190px; }
  .page-shell { padding-right: 32px; padding-left: 32px; }
  .nav-wrap { padding: 8px; flex-wrap: nowrap; }
  .primary-nav { width: auto; flex: 0 0 auto; flex-wrap: nowrap; }
  .primary-nav a { min-height: 30px; }
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
  h1, .page-intro h1 { font-size: 28px; }
  .hero { padding-top: 0; }
  .summary, .public-facts, .metric-band, .diagnostic-ledger,
  .methods-grid, .download-list, .insight-grid { grid-template-columns: 1fr; }
  .score, .score:first-child, .score:nth-child(2), .score:nth-child(3),
  .metric, .public-facts div, .public-facts div:first-child,
  .public-facts div:nth-child(2), .public-facts div:nth-child(3) {
    padding: 13px 0;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .score:last-child, .metric:last-child, .public-facts div:last-child { border-bottom: 0; }
  .source-note { margin-left: 0; }
  .viz-frame { min-width: 720px; }
  .footer-wrap { padding: 18px 20px; }
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


def _navigation(active: str, family: str) -> str:
    nested = family == "analysis"
    prefix = "../" if nested else ""
    pages = ANALYSIS_PAGES if nested else PUBLIC_PAGES
    links = []
    for filename, label in pages:
        current = ' aria-current="page"' if filename == active else ""
        links.append(f'<a href="{filename}"{current}>{html.escape(label)}</a>')
    public_current = ' aria-current="true"' if family == "public" else ""
    analysis_current = ' aria-current="true"' if family == "analysis" else ""
    family_label = "Daily public report" if family == "public" else "72-hour analysis"
    return (
        f'<div class="nav-wrap"><a class="brand" href="{prefix}index.html">Atlas</a>'
        f'<span class="nav-label">Report edition</span>'
        f'<div class="report-switch" aria-label="Report edition"><a href="{prefix}index.html"{public_current}>Public report</a>'
        f'<a href="{prefix}analysis/index.html"{analysis_current}>Meteorological analysis</a></div>'
        f'<span class="nav-label">{family_label}</span>'
        f'<nav class="primary-nav" aria-label="Primary">{"".join(links)}</nav>'
        f'<div class="sidebar-note"><strong>Debrecen, Hungary</strong>'
        f'Daily public record and rolling expert analysis.</div></div>'
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
    family: str,
    edition_notice: str | None = None,
) -> str:
    title = config.project.name if active == "index.html" else f"{page_name} | {config.project.name}"
    notice_line = (
        f'  <div class="edition-notice" role="note">{html.escape(edition_notice)}</div>\n'
        if edition_notice
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <meta name="description" content="{html.escape(description)}">
  <style>{SHARED_CSS}{DATA_FIRST_CSS}</style>
</head>
<body>
  <div class="app-shell">
    <header class="site-header" id="site-navigation">{_navigation(active, family)}</header>
    <div class="sidebar-scrim" id="sidebar-scrim"></div>
    <div class="workspace">
      <header class="report-topbar">
        <button class="menu-button" id="menu-button" type="button" aria-label="Open navigation">&#9776;</button>
        <div class="breadcrumbs"><span class="optional">Atlas</span><span class="optional">/</span><span>{html.escape('Daily report' if family == 'public' else '72-hour analysis')}</span><span>/</span><strong>{html.escape(page_name)}</strong></div>
      </header>
{notice_line}      <main><div class="page-shell">{content}</div></main>
      <footer><div class="footer-wrap">Last updated {updated}. Debrecen weather with Hungary-wide electricity context.</div></footer>
    </div>
  </div>
  <script>
    const navigation = document.querySelector('#site-navigation');
    const scrim = document.querySelector('#sidebar-scrim');
    const menuButton = document.querySelector('#menu-button');
    const setMenu = open => {{
      navigation.classList.toggle('open', open);
      scrim.classList.toggle('open', open);
    }};
    menuButton.addEventListener('click', () => setMenu(true));
    scrim.addEventListener('click', () => setMenu(false));
    navigation.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setMenu(false)));
  </script>
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
    for source in site_dir.iterdir():
        if source.name == ".gitkeep":
            continue
        target = archive_dir / source.name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return archive_dir / "index.html"


def archive_public_site(
    site_dir: Path,
    archive_dir: Path,
    asset_names: set[str],
) -> Path:
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    (archive_dir / "assets").mkdir(parents=True, exist_ok=True)
    for filename, _ in PUBLIC_PAGES:
        source = site_dir / filename
        if source.exists():
            shutil.copy2(source, archive_dir / filename)
    for name in asset_names:
        source = site_dir / "assets" / name
        if source.exists():
            shutil.copy2(source, archive_dir / "assets" / name)
    return archive_dir / "index.html"


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
    figure_paths: dict[str, Path],
    processed_paths: dict[str, Path],
    site_dir: Path | None = None,
    quality_notes: list[str] | None = None,
    edition_notice: str | None = None,
) -> Path:
    site_dir = site_dir or config.outputs.site_dir
    site_dir.mkdir(parents=True, exist_ok=True)
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
        "regime": asdict(regime),
        "daily_regime": asdict(daily_regime),
        "anomalies": [asdict(item) for item in anomalies],
        "quality_notes": quality_notes or [],
    }
    (data_dir / "summary.json").write_text(
        json.dumps(json_ready(payload), indent=2, allow_nan=False), encoding="utf-8"
    )

    period_label = f"{config.location.name}, {config.location.region} - {period_start} to {period_end}"
    daily_label = f"{config.location.name}, {config.location.region} - {daily_date}"
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
                f'<div class="evidence-meta">{event.confidence:.0%} confidence | {html.escape(event.source)}</div></div></li>'
            )
        return "".join(items)

    day_regime_label = daily_regime.label.replace(" period", " day")
    day_briefing = daily_regime.briefing.replace(daily_regime.label, day_regime_label, 1).replace(
        "period solar radiation", "daily solar radiation"
    )
    public_overview = f"""
<header class="hero">
  <div>
    <div class="eyebrow">Daily public report | {html.escape(daily_label)}</div>
    <h1>{html.escape(config.project.name)}</h1>
    <p class="hero-regime">{html.escape(day_regime_label)}</p>
    <p class="brief">{html.escape(day_briefing)}</p>
    <p class="meta">A concise account of the last complete day in Debrecen.</p>
    <div class="source-key" aria-label="Daily report evidence">
      <span class="source-chip observed"><b>OBS</b> Debrecen Airport</span>
      <span class="source-chip gridded"><b>GRID</b> Open-Meteo</span>
      <span class="source-chip remote"><b>REMOTE</b> Radar + lightning</span>
      <span class="source-chip derived"><b>MODEL</b> Renewable yield</span>
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
    public_overview += _plot_section(
        "Yesterday Hour By Hour",
        public_figures["daily_meteogram"],
        "Daily Debrecen meteogram",
        "Read downward through temperature and dew point, pressure, wind and gusts, precipitation, then cloud and solar radiation.",
        "meteogram",
    )
    public_overview += f'<p class="public-lead"><strong>Deterministic interpretation.</strong> Yesterday was classified as {html.escape(day_regime_label.lower())}. Atlas detected {len(daily_events)} notable weather phenomenon candidate(s), {len(daily_lightning):,} lightning event(s) within {config.hungaromet.lightning_radius_km:.0f} km, and a maximum sampled radar reflectivity of {_fmt(daily_radar_max)} dBZ.</p>'

    public_weather = _page_intro(
        "Yesterday's Weather",
        "The observed day at Debrecen Airport with gridded context used where continuous station data is unavailable.",
        daily_label,
    )
    public_weather += f'<p class="analysis-lead"><strong>Observed at the airport.</strong> Mean {_fmt(daily_observed_temp)} C, {_fmt(daily_observed_rain)} mm precipitation and a peak gust of {_fmt(daily_observed_gust)} m/s.</p>'
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
      <span class="source-chip observed"><b>OBS</b> Station 64711</span>
      <span class="source-chip remote"><b>REMOTE</b> Radar + LINET + MSG</span>
      <span class="source-chip gridded"><b>GRID</b> ERA5 + model levels</span>
      <span class="source-chip derived"><b>MODEL</b> Energy + diagnostics</span>
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
<p class="analysis-lead"><strong>Deterministic interpretation.</strong> {html.escape(regime.briefing)} Atlas found {len(fronts.events)} objective frontal passage candidate(s), {lightning_count:,} lightning event(s) within {config.hungaromet.lightning_radius_km:.0f} km, and a maximum sampled radar reflectivity of {_fmt(radar_max)} dBZ.</p>
<div class="insight-grid">
  <article class="insight"><span class="provenance">Observed</span><h3>Debrecen Airport</h3><p>Mean {_fmt(observed_temp)} C, {_fmt(observed_rain)} mm precipitation and a peak gust of {_fmt(observed_gust)} m/s from station {station.station_id}.</p></article>
  <article class="insight"><span class="provenance">Radar + LINET</span><h3>Storm character</h3><p>{lightning_count:,} lightning events were inside the study radius; the closest was {_fmt(closest_flash)} km from Debrecen.</p></article>
  <article class="insight"><span class="provenance">Model-derived</span><h3>Atmospheric column</h3><p>Selected-profile surface-based CAPE was {_fmt(cape, 0)} J/kg and boundary-layer height was {_fmt(pbl, 0)} m.</p></article>
  <article class="insight"><span class="provenance">ERA5 analog</span><h3>Historical likeness</h3><p>{html.escape(best_analog.start_date + ' to ' + best_analog.end_date + ': ' + best_analog.character) if best_analog else 'No robust seasonal analog was available.'}</p></article>
</div>
"""

    weather = _page_intro(
        "Surface And Synoptic Analysis",
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
        "Selectable Synoptic Dynamics",
        figures["synoptic_evolution"],
        "Animated Central European synoptic analysis",
        "Select air-mass, 300 hPa jet, 500 hPa vorticity, 700 hPa moisture/ascent, or 850 hPa theta-e/frontogenesis mode, then animate the shared timeline.",
        "synoptic",
    )
    weather += _plot_section("Wind Regime", figures["wind_rose"], "Interactive wind rose", "Spokes point toward the direction the wind came from. Length is frequency and color separates speed classes.", "context")
    weather += _plot_section("Pressure And Frontal Tendency", figures["pressure_tendency"], "Interactive pressure tendency", "Six-hour pressure changes expose troughs, frontal passages and the establishment or breakdown of anticyclonic conditions.", "context")

    storms = _page_intro("Storms And Satellite", "A synchronized Meteosat, radar, lightning and objective-phenomena reconstruction of the complete 72-hour period.", period_label)
    storms += f'<p class="analysis-lead"><strong>Event diagnosis.</strong> Radar reached {_fmt(radar_max)} dBZ in the sampled domain. LINET registered {lightning_count:,} events within {config.hungaromet.lightning_radius_km:.0f} km, and Atlas identified {len(phenomena.events)} objective phenomenon candidate(s).</p>'
    storms += _plot_section("Meteosat, Radar And Lightning Diary", figures["satellite_diary"], "Synchronized Meteosat satellite diary", "Choose Airmass, Natural Colour, Night Microphysics, Fog RGB or InfraCloud; play the frames while the cursor follows the nearest radar and lightning observations.", "satellite", "HungaroMet MSG imagery sampled every three hours for a practical self-contained archive.")
    storms += _plot_section("Objective Phenomena Strip", figures["phenomena_timeline"], "Objective weather phenomena chronology", "Each segment is a threshold-based candidate. Hover to inspect evidence, confidence and provenance.", "phenomena")
    storms += f'<section class="content-section"><h2>Evidence ledger</h2><ul class="event-list">{phenomenon_items(phenomena.events, "No objective phenomenon detected")}</ul></section>'
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
    climate = _page_intro("Debrecen Climate And Analogs", "The current period compared with the 1991-2020 standard normal, the recent decade, the full ERA5 record and closest seasonal analogs.", period_label)
    climate += _plot_section("Standard Normal, Recent Decade And Full Record", figures["climate_reference"], "Climatological reference comparison", "Compare standardized anomalies against 1991-2020 and the recent decade, then inspect the empirical percentile across the full ERA5 record.", "climate-reference")
    climate += f'<p class="analysis-lead"><strong>Historical likeness.</strong> {html.escape(best_analog.start_date + " to " + best_analog.end_date) + " was the closest match, described as " + html.escape(best_analog.character) + "." if best_analog else "No robust analog could be selected."}</p><section class="content-section"><h2>Closest seasonal analogs</h2><div class="analog-list">{analog_rows}</div></section>'
    climate += _plot_section("Seven-Day Weather Diary", figures["seven_day_context"], "Seven-day weather context", "The highlighted final three days are the active report; the preceding four days preserve the transition into the current regime.", "context")
    climate += _plot_section("Anomaly Structure", figures["anomaly_bars"], "Weather anomaly bars", "Bars show standard deviations from the same calendar window in prior years. Sign means above or below normal, not favorable or unfavorable.")
    climate += _plot_section("Daily Regime Evolution", figures["regime_strip"], "Daily regime strip", "Each segment is one local day classified with transparent weather rules.", "compact")
    climate += _plot_section("Solar Climatology", figures["solar_diurnal"], "Solar diurnal curves", "Daily radiation profiles are compared with the historical median to distinguish clear, overcast and intermittently cloudy solar regimes.")

    electricity_page = _page_intro("Land Surface And Energy", "Ninety-day soil and atmospheric water balance followed by physical renewable yields and Hungary-wide electricity-system context.", period_label)
    electricity_page += f'<p class="analysis-lead"><strong>{html.escape(land.moisture_context)}.</strong> The 90-day precipitation-minus-ET0 balance was {_fmt(land.metrics.get("water_balance_90d_mm", float("nan")))} mm, at the {_fmt(land.water_balance_percentiles.get(90, float("nan")), 0)}th percentile of 1991-2020.</p>'
    electricity_page += _plot_section("Land Surface And Water Balance", figures["land_surface"], "Soil, VPD, ET0 and water-balance analysis", "Read soil temperature and moisture by depth, atmospheric vapour-pressure deficit, ET0, and daily/cumulative precipitation minus ET0 across the preceding 90 days.", "land-surface", "Open-Meteo best-match gridded land fields; the 1991-2020 reference is fixed ERA5, and water balance excludes runoff and irrigation.")
    electricity_page += f'<p class="analysis-lead"><strong>Weather translated into production.</strong> A fixed south-facing reference array produced an estimated {_fmt(physical_energy.pv_yield_kwh_per_kwp, 1)} kWh/kWp. A generic 100 m turbine produced {_fmt(physical_energy.wind_full_load_hours, 1)} full-load hours at a mean capacity factor of {_fmt(physical_energy.wind_capacity_factor_pct, 1)}%.</p><div class="metric-band" aria-label="Physical and system energy summary"><div class="metric"><span>PV weather yield</span><strong>{_fmt(physical_energy.pv_yield_kwh_per_kwp, 1)}</strong><span>kWh/kWp</span></div><div class="metric"><span>Wind capacity factor</span><strong>{_fmt(physical_energy.wind_capacity_factor_pct, 1)}</strong><span>percent</span></div><div class="metric"><span>Hungary average load</span><strong>{_fmt_grouped(electricity.average_load_mw)}</strong><span>MW</span></div><div class="metric"><span>Day-ahead price</span><strong>{_fmt(electricity.average_price_eur_mwh, 0)}</strong><span>EUR/MWh</span></div></div>'
    electricity_page += _plot_section("Physical PV And Wind Yield", figures["physical_energy"], "Physically based renewable weather yield", "PV uses solar position, plane-of-array irradiance and cell-temperature derating. Wind uses 100 m speed, moist-air density and a generic turbine power curve.", "physical-energy")
    electricity_page += _plot_section("Solar-Wind Weather Quadrant", figures["energy_quadrant"], "Solar and wind potential quadrant", "The indices provide a normalized climatological view; the physical-yield panel above provides the engineering interpretation.", "context")
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
        ("Land-surface hourly context", data_links.get("land_surface_hourly")),
        ("Land-surface daily context", data_links.get("land_surface_daily")),
        ("Machine-readable summary", "../data/summary.json"),
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
    <p>HungaroMet supplies Debrecen Airport observations, composite radar, LINET lightning and Meteosat imagery. Open-Meteo supplies the continuous gridded surface record, pressure-level model fields, synoptic grid, land fields and ERA5 climate archive. Standard normals use 1991-2020; the recent comparison retains the prior {config.baseline.years} years and is stored in {html.escape(baseline_period)}.</p>
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

    public_documents = {
        "index.html": ("Daily Overview", "Daily public weather report for Debrecen.", public_overview),
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
            ),
            encoding="utf-8",
        )

    analysis_documents = {
        "index.html": ("Analysis Overview", "Rolling 72-hour Debrecen meteorological analysis.", analysis_overview),
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
            ),
            encoding="utf-8",
        )

    return site_dir / "index.html"
