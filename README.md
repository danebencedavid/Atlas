# Atlas

Atlas builds a practical weekly weather-regime and renewable-energy weather
dashboard for Debrecen, Hungary. It describes the most recent complete local
Monday-Sunday week, compares it with a multi-year normal for the same calendar
window, and explains what the week implied for solar and wind potential.

This project remains focused on Debrecen only.

The main pipeline uses real public APIs:

- Open-Meteo Historical Weather API for hourly recent and historical weather
- NASA POWER Hourly API as the preferred future solar/energy cross-check
- HungaroMet ODP as the preferred future official Hungarian station/climate
  data source

Atlas is descriptive, diagnostic, climatological, and energy-oriented. It is
not a forecast calibration project.

## Research Question

What kind of weather week did Debrecen just have, how unusual was it compared
with normal, and what did it imply for solar and wind energy potential?

## Quick Start

```powershell
python -m pip install -e ".[dev]"
atlas --refresh
```

If the package is not installed, run from the repo root:

```powershell
$env:PYTHONPATH="src"
python -m atlas.cli --refresh
```

The command creates:

```text
data/raw/open_meteo_localweek_*.json
data/processed/current_hourly.csv
data/processed/weekly_metrics.csv
data/processed/baseline_metrics.csv
data/processed/anomalies.csv
data/processed/summary.json
reports/weeks/YYYY-MM-DD_YYYY-MM-DD/index.html
reports/weeks/YYYY-MM-DD_YYYY-MM-DD/assets/*.html
reports/weeks/YYYY-MM-DD_YYYY-MM-DD/data/*.csv
site/index.html
site/assets/*.html
site/data/*.csv
```

## Main Commands

```powershell
atlas
atlas --refresh
atlas --week-start 2026-07-20
atlas --today 2026-07-27
atlas --config configs/atlas.yml --refresh
```

## GitHub Pages

The workflow in `.github/workflows/pages.yml` builds and deploys the static
dashboard. After pushing to GitHub, set:

```text
Settings > Pages > Build and deployment > Source > GitHub Actions
```

Then run the `Build and Deploy Atlas` workflow, or wait for the weekly Monday
schedule.

The generated static site lives in `site/` locally and is deployed as a Pages
artifact in CI. Each successful workflow also commits a versioned weekly report
archive under `reports/weeks/` so the interactive plots, dashboard HTML, and
data tables are preserved in the repository.

The GitHub Actions build uses Open-Meteo requests with retry/backoff and
local-week completeness checks. If the just-ended week is not complete in the
archive API yet, Atlas steps back to the latest complete week within the
configured lag window instead of publishing a partial report.

## Project Structure

```text
configs/                 Debrecen-only configuration
data/raw/                Cached Open-Meteo API responses
data/processed/          Latest processed metrics and CSV outputs
docs/                    Methods and data-source notes
reports/figures/         Legacy scratch figure directory
reports/weeks/           Versioned weekly dashboard and plot archives
site/                    Latest GitHub Pages static site artifact
src/atlas/               Ingestion, baseline, anomaly, regime, energy, plots, CLI
tests/                   Lightweight offline tests
```

## Current Scope

Atlas currently targets Debrecen using point coordinates near the city. The MVP
computes:

- weekly regime label
- one-sentence weather briefing
- temperature, precipitation, wind, pressure, cloud, and solar anomalies
- solar potential index
- wind potential index
- combined renewable weather score
- calm-wind penalty
- cloud penalty
- historical percentile ranks

## Interactive Visuals

Atlas uses Plotly HTML figures, so readers can zoom, pan, hover, toggle series,
box-select, lasso-select where applicable, draw annotations, and export views
directly in the browser.

Included visuals:

- interactive weekly meteogram
- interactive wind rose
- interactive pressure tendency plot
- interactive temperature-dew point spread plot
- interactive solar radiation diurnal curves
- interactive weather anomaly bars
- interactive solar-wind energy quadrant
- interactive daily regime classification strip

## Data Sources

Current source:

- Open-Meteo Historical Weather API

Worth adding next:

- HungaroMet ODP for official Hungarian observations and climate station data
- NASA POWER Hourly API for solar radiation and renewable-energy weather checks
- NOAA Aviation Weather API for live LHDC METAR sanity checks

Less central for this project:

- NOAA CDO/GHCN, because it needs a token and is better suited to daily climate
  checks than the hourly weekly dashboard

See `docs/data_sources.md` and `docs/methods.md`.
