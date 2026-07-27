from __future__ import annotations

import html
import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from atlas.anomalies import Anomaly
from atlas.config import AtlasConfig
from atlas.energy import EnergyIndex
from atlas.regimes import RegimeClassification


def _fmt(value: float, digits: int = 1) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.{digits}f}"


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


def build_site(
    config: AtlasConfig,
    week_start: str,
    week_end: str,
    current_metrics: dict[str, float],
    baseline_metrics: dict[str, float],
    anomalies: list[Anomaly],
    energy: EnergyIndex,
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

    anomalies_rows = "\n".join(
        f"<tr><th>{html.escape(item.label)}</th><td>{_fmt(item.value)}</td><td>{_fmt(item.baseline_mean)}</td>"
        f"<td>{item.anomaly:+.1f} {html.escape(item.unit)}</td><td>{_fmt(item.percentile, 0)}th</td></tr>"
        for item in anomalies
    )
    signal_items = "\n".join(f"<li>{html.escape(signal)}</li>" for signal in regime.signals)
    quality_items = "\n".join(f"<li>{html.escape(note)}</li>" for note in (quality_notes or []))
    baseline_period = processed_paths.get("baseline_metrics", Path("baseline_metrics.csv")).name

    payload: dict[str, Any] = {
        "week_start": week_start,
        "week_end": week_end,
        "current_metrics": current_metrics,
        "baseline_metrics": baseline_metrics,
        "energy": asdict(energy),
        "regime": asdict(regime),
        "anomalies": [asdict(item) for item in anomalies],
        "quality_notes": quality_notes or [],
    }
    (data_dir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(config.project.name)} - {html.escape(config.location.name)} Weekly Weather Dashboard</title>
  <meta name="description" content="Weekly weather anomaly and renewable-energy weather report for {html.escape(config.location.name)}, {html.escape(config.location.region)}.">
  <style>
    :root {{
      --ink: #172033;
      --muted: #667085;
      --line: #d9e0ea;
      --paper: #f7f9fc;
      --panel: #ffffff;
      --blue: #2563eb;
      --red: #c2410c;
      --green: #047857;
      --gold: #b7791f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--paper);
      line-height: 1.5;
    }}
    header {{
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero {{
      display: grid;
      gap: 22px;
      grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.9fr);
      align-items: end;
      min-height: 420px;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: clamp(3rem, 8vw, 6.7rem);
      letter-spacing: 0;
      line-height: 0.95;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 1.35rem;
      letter-spacing: 0;
    }}
    .eyebrow {{
      color: var(--blue);
      font-weight: 750;
      text-transform: uppercase;
      font-size: 0.82rem;
    }}
    .brief {{
      max-width: 780px;
      font-size: 1.18rem;
      color: #344054;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .score, section, .table-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    }}
    .score {{ padding: 16px; }}
    .score strong {{
      display: block;
      font-size: 2.1rem;
      line-height: 1.1;
    }}
    .score span, .meta, footer {{
      color: var(--muted);
      font-size: 0.93rem;
    }}
    main .wrap {{
      display: grid;
      gap: 18px;
    }}
    section {{ padding: 18px; }}
    .grid-two {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    img {{
      display: block;
      width: 100%;
      height: auto;
      border: 1px solid #eef2f7;
      border-radius: 6px;
      background: #ffffff;
    }}
    .viz-frame {{
      display: block;
      width: 100%;
      min-height: 560px;
      border: 1px solid #eef2f7;
      border-radius: 6px;
      background: #ffffff;
    }}
    .viz-frame.tall {{ min-height: 980px; }}
    .viz-frame.compact {{ min-height: 280px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: right;
    }}
    th {{ text-align: left; }}
    .notes {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }}
    a {{ color: var(--blue); }}
    ul {{ margin: 8px 0 0; padding-left: 20px; }}
    @media (max-width: 820px) {{
      .hero, .grid-two, .notes {{ grid-template-columns: 1fr; }}
      .summary {{ grid-template-columns: 1fr; }}
      .wrap {{ padding: 18px; }}
      h1 {{ font-size: 3.2rem; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap hero">
      <div>
        <div class="eyebrow">{html.escape(config.location.name)}, {html.escape(config.location.region)} - {html.escape(week_start)} to {html.escape(week_end)}</div>
        <h1>{html.escape(config.project.name)}</h1>
        <h2>{html.escape(regime.label)}</h2>
        <p class="brief">{html.escape(regime.briefing)}</p>
        <p class="meta">{html.escape(config.project.tagline)}</p>
      </div>
      <div class="summary" aria-label="Renewable weather scores">
        <div class="score"><span>Solar index</span><strong>{_fmt(energy.solar_index, 0)}</strong><span>{_fmt(energy.cloud_penalty)} cloud penalty</span></div>
        <div class="score"><span>Wind index</span><strong>{_fmt(energy.wind_index, 0)}</strong><span>{_fmt(energy.calm_wind_penalty)} calm penalty</span></div>
        <div class="score"><span>Combined score</span><strong>{_fmt(energy.combined_score, 0)}</strong><span>{html.escape(energy.label)}</span></div>
      </div>
    </div>
  </header>
  <main>
    <div class="wrap">
      <section>
        <h2>Weekly Meteogram</h2>
        <iframe class="viz-frame tall" src="{figures["meteogram"]}" title="Interactive weekly meteogram"></iframe>
      </section>
      <div class="grid-two">
        <section>
          <h2>Anomaly Summary</h2>
          <iframe class="viz-frame" src="{figures["anomaly_bars"]}" title="Interactive bar chart of weekly weather anomalies"></iframe>
        </section>
        <section>
          <h2>Solar-Wind Energy Quadrant</h2>
          <iframe class="viz-frame" src="{figures["energy_quadrant"]}" title="Interactive solar and wind potential quadrant chart"></iframe>
        </section>
      </div>
      <div class="grid-two">
        <section>
          <h2>Wind Rose</h2>
          <iframe class="viz-frame" src="{figures["wind_rose"]}" title="Interactive wind rose with wind direction frequencies by speed bin"></iframe>
        </section>
        <section>
          <h2>Pressure Tendency</h2>
          <iframe class="viz-frame" src="{figures["pressure_tendency"]}" title="Interactive sea-level pressure and six-hour pressure tendency"></iframe>
        </section>
      </div>
      <div class="grid-two">
        <section>
          <h2>Temperature-Dew Point Spread</h2>
          <iframe class="viz-frame" src="{figures["dewpoint_spread"]}" title="Interactive temperature and dew point with shaded humid periods"></iframe>
        </section>
        <section>
          <h2>Solar Diurnal Curves</h2>
          <iframe class="viz-frame" src="{figures["solar_diurnal"]}" title="Interactive daily shortwave radiation curves compared with baseline median"></iframe>
        </section>
      </div>
      <section>
        <h2>Regime Strip</h2>
        <iframe class="viz-frame compact" src="{figures["regime_strip"]}" title="Interactive daily weather regime classification strip"></iframe>
      </section>
      <section class="table-panel">
        <h2>Historical Percentile Ranks</h2>
        <table>
          <thead><tr><th>Metric</th><th>This week</th><th>Baseline mean</th><th>Anomaly</th><th>Percentile</th></tr></thead>
          <tbody>{anomalies_rows}</tbody>
        </table>
      </section>
      <div class="notes">
        <section>
          <h2>Classification Signals</h2>
          <ul>{signal_items}</ul>
        </section>
        <section>
          <h2>Methods And Data</h2>
          <p>Hourly observations are fetched from the Open-Meteo Historical Weather API. The baseline uses the same calendar-week window over the prior {config.baseline.years} years and is stored in {html.escape(baseline_period)}.</p>
          <ul>{quality_items}</ul>
          <p>Outputs: <a href="{data_links.get("weekly_metrics", "data/weekly_metrics.csv")}">weekly metrics CSV</a>, <a href="{data_links.get("anomalies", "data/anomalies.csv")}">anomalies CSV</a>, <a href="data/summary.json">summary JSON</a>.</p>
        </section>
      </div>
    </div>
  </main>
  <footer>
    <div class="wrap">Last updated {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}.</div>
  </footer>
</body>
</html>
"""
    target = site_dir / "index.html"
    target.write_text(html_doc, encoding="utf-8")
    return target
