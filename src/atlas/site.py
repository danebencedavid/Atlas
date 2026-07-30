from __future__ import annotations

import html
import json
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from atlas.anomalies import Anomaly
from atlas.config import AtlasConfig
from atlas.electricity import ElectricitySummary
from atlas.energy import EnergyIndex
from atlas.profile import ModelProfile
from atlas.regimes import RegimeClassification


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


def archive_site(site_dir: Path, archive_dir: Path) -> Path:
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    for name in ["assets", "data"]:
        source = site_dir / name
        if source.exists():
            shutil.copytree(source, archive_dir / name)
    shutil.copy2(site_dir / "index.html", archive_dir / "index.html")
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
    electricity_note_items = "\n".join(f"<li>{html.escape(note)}</li>" for note in electricity_notes)
    profile_note_items = "\n".join(f"<li>{html.escape(note)}</li>" for note in profile.notes)
    baseline_period = processed_paths.get("baseline_metrics", Path("baseline_metrics.csv")).name

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
  <title>{html.escape(config.project.name)} - {html.escape(config.location.name)} Rolling Weather Dashboard</title>
  <meta name="description" content="Rolling three-day weather anomaly, electricity, and renewable-energy report for {html.escape(config.location.name)}, {html.escape(config.location.region)}.">
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
      overflow-x: hidden;
    }}
    header {{
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    .wrap {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 28px;
    }}
    .hero {{
      display: grid;
      gap: 22px;
      grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.9fr);
      align-items: end;
      min-height: 350px;
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
      grid-template-columns: minmax(0, 1fr);
      gap: 24px;
      width: 100%;
    }}
    main .wrap > *, section, .score {{ min-width: 0; }}
    section {{ padding: 24px; }}
    .electricity-summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin: 0 0 18px;
    }}
    img {{
      display: block;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      height: auto;
      border: 1px solid #eef2f7;
      border-radius: 6px;
      background: #ffffff;
    }}
    .viz-frame {{
      display: block;
      width: 100%;
      height: 620px;
      border: 1px solid #eef2f7;
      border-radius: 6px;
      background: #ffffff;
      overflow: hidden;
    }}
    .viz-frame.tall {{ height: 1020px; }}
    .viz-frame.context {{ height: 760px; }}
    .viz-frame.electricity {{ height: 860px; }}
    .viz-frame.relationships {{ height: 820px; }}
    .viz-frame.profile {{ height: 860px; }}
    .viz-frame.compact {{ height: 300px; }}
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
      gap: 24px;
    }}
    .table-scroll {{ overflow-x: auto; }}
    .source-note {{
      margin: -4px 0 18px;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    a {{ color: var(--blue); }}
    ul {{ margin: 8px 0 0; padding-left: 20px; }}
    @media (max-width: 820px) {{
      .hero, .notes {{ grid-template-columns: 1fr; }}
      .summary, .electricity-summary {{ grid-template-columns: 1fr; }}
      .wrap {{ padding: 18px; }}
      h1 {{ font-size: 3.2rem; }}
      section {{ padding: 14px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap hero">
      <div>
        <div class="eyebrow">{html.escape(config.location.name)}, {html.escape(config.location.region)} - {html.escape(period_start)} to {html.escape(period_end)}</div>
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
        <h2>Rolling 72-Hour Meteogram</h2>
        <iframe class="viz-frame tall" src="{figures["meteogram"]}" title="Interactive rolling three-day meteogram" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Seven-Day Archive Context</h2>
        <iframe class="viz-frame context" src="{figures["seven_day_context"]}" title="Interactive seven-day weather context with the current three-day report highlighted" loading="lazy" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Anomaly Summary</h2>
        <iframe class="viz-frame" src="{figures["anomaly_bars"]}" title="Interactive bar chart of three-day weather anomalies" loading="lazy" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Solar-Wind Energy Quadrant</h2>
        <iframe class="viz-frame context" src="{figures["energy_quadrant"]}" title="Interactive solar and wind potential quadrant chart" loading="lazy" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Hungary Electricity Context</h2>
        <p class="source-note">National electricity data from Energy-Charts and ENTSO-E is shown as context for Debrecen's local weather.</p>
        <div class="electricity-summary" aria-label="Hungary electricity summary">
          <div class="score"><span>Average load</span><strong>{_fmt_grouped(electricity.average_load_mw)}</strong><span>MW</span></div>
          <div class="score"><span>Solar generation</span><strong>{_fmt_grouped(electricity.solar_generation_mwh)}</strong><span>MWh over period</span></div>
          <div class="score"><span>Wind generation</span><strong>{_fmt_grouped(electricity.wind_generation_mwh)}</strong><span>MWh over period</span></div>
          <div class="score"><span>Average day-ahead price</span><strong>{_fmt(electricity.average_price_eur_mwh, 0)}</strong><span>EUR/MWh</span></div>
        </div>
        <iframe class="viz-frame electricity" src="{figures["electricity_overview"]}" title="Interactive Hungary electricity load, renewable generation, and price chart" loading="lazy" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Weather-Electricity Relationships</h2>
        <iframe class="viz-frame relationships" src="{figures["weather_electricity_links"]}" title="Interactive comparison of Debrecen weather and Hungary electricity generation" loading="lazy" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Wind Rose</h2>
        <iframe class="viz-frame context" src="{figures["wind_rose"]}" title="Interactive wind rose with wind direction frequencies by speed bin" loading="lazy" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Pressure Tendency</h2>
        <iframe class="viz-frame context" src="{figures["pressure_tendency"]}" title="Interactive sea-level pressure and six-hour pressure tendency" loading="lazy" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Temperature-Dew Point Spread</h2>
        <iframe class="viz-frame" src="{figures["dewpoint_spread"]}" title="Interactive temperature and dew point with shaded humid periods" loading="lazy" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Solar Diurnal Curves</h2>
        <iframe class="viz-frame" src="{figures["solar_diurnal"]}" title="Interactive daily shortwave radiation curves compared with baseline median" loading="lazy" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Advanced Meteorological Diagnostic</h2>
        <p class="source-note">Model-derived profile near Debrecen. This is a Skew-T-style diagnostic, not an observed radiosonde.</p>
        <iframe class="viz-frame profile" src="{figures["model_profile"]}" title="Interactive Skew-T-style model atmospheric profile for Debrecen" loading="lazy" scrolling="no"></iframe>
      </section>
      <section>
        <h2>Regime Strip</h2>
        <iframe class="viz-frame compact" src="{figures["regime_strip"]}" title="Interactive daily weather regime classification strip" loading="lazy" scrolling="no"></iframe>
      </section>
      <section class="table-panel">
        <h2>Historical Percentile Ranks</h2>
        <div class="table-scroll">
          <table>
            <thead><tr><th>Metric</th><th>This period</th><th>Baseline mean</th><th>Anomaly</th><th>Percentile</th></tr></thead>
            <tbody>{anomalies_rows}</tbody>
          </table>
        </div>
      </section>
      <div class="notes">
        <section>
          <h2>Classification Signals</h2>
          <ul>{signal_items}</ul>
        </section>
        <section>
          <h2>Methods And Data</h2>
          <p>Hourly weather fields are fetched from the Open-Meteo Historical Weather API. The baseline uses the same three-day calendar window over the prior {config.baseline.years} years and is stored in {html.escape(baseline_period)}.</p>
          <ul>{quality_items}</ul>
          <ul>{electricity_note_items}</ul>
          <ul>{profile_note_items}</ul>
          <p>Outputs: <a href="{data_links.get("period_metrics", "data/period_metrics.csv")}">period metrics CSV</a>, <a href="{data_links.get("electricity", "data/electricity.csv")}">electricity CSV</a>, <a href="{data_links.get("anomalies", "data/anomalies.csv")}">anomalies CSV</a>, <a href="data/summary.json">summary JSON</a>.</p>
        </section>
      </div>
    </div>
  </main>
  <footer>
    <div class="wrap">Last updated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}.</div>
  </footer>
  <script>
    const resizePlot = (frame) => {{
      try {{
        const doc = frame.contentDocument;
        if (!doc) return;
        const height = Math.max(doc.body.scrollHeight, doc.documentElement.scrollHeight);
        if (height > 200) frame.style.height = `${{height + 4}}px`;
      }} catch (_error) {{
        // Static same-origin plots normally allow sizing; fixed CSS heights remain as fallback.
      }}
    }};
    document.querySelectorAll(".viz-frame").forEach((frame) => {{
      frame.addEventListener("load", () => {{
        resizePlot(frame);
        window.setTimeout(() => resizePlot(frame), 350);
      }});
    }});
  </script>
</body>
</html>
"""
    target = site_dir / "index.html"
    target.write_text(html_doc, encoding="utf-8")
    return target
