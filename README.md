# Atlas: Rolling Weather and Electricity Diagnostics for Debrecen

Atlas builds a practical three-day weather, climatology, and renewable-energy
situation report for Debrecen, Hungary. It describes the latest 72 complete
local hours, compares them with the same calendar window in prior years, and
connects Debrecen's weather with Hungary's electricity-system conditions.

The project remains focused on Debrecen. National electricity data is included
only as system context for the local weather analysis.

The main pipeline uses real public APIs:

- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
  for recent and baseline hourly weather
- [Energy-Charts API](https://api.energy-charts.info/) for Hungary generation,
  load, cross-border flow, and day-ahead price data, primarily sourced from
  ENTSO-E
- [Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api)
  for pressure-level model profiles near Debrecen

No API key or repository secret is required.

## Research Question

What kind of weather did Debrecen have over the last three complete days, how
unusual was it compared with normal, and how did it relate to solar, wind, and
electricity-system conditions?

Atlas is descriptive, diagnostic, climatological, and energy-oriented. It is
not a forecast-calibration project.

## Quick Start

```powershell
python -m pip install -e ".[dev]"
atlas --refresh
```

If the package is not installed, run from the repository root:

```powershell
$env:PYTHONPATH="src"
python -m atlas.cli --refresh
```

The command creates:

```text
data/raw/open_meteo_localperiod_*.json
data/raw/energy_charts_*.json
data/raw/open_meteo_model_profile_*.json
data/processed/current_hourly.csv
data/processed/seven_day_context_hourly.csv
data/processed/period_metrics.csv
data/processed/baseline_metrics.csv
data/processed/anomalies.csv
data/processed/electricity.csv
data/processed/model_profile.csv
data/processed/summary.json
reports/periods/YYYY-MM-DD_YYYY-MM-DD/index.html
reports/periods/YYYY-MM-DD_YYYY-MM-DD/assets/*.html
reports/periods/YYYY-MM-DD_YYYY-MM-DD/data/*.csv
site/index.html
site/assets/*.html
site/data/*.csv
```

## Main Commands

```powershell
atlas
atlas --refresh
atlas --period-start 2026-07-27
atlas --today 2026-07-30
atlas --config configs/atlas.yml --refresh
```

`--week-start` remains as a compatibility alias for `--period-start`.

## Dashboard

The report is deliberately arranged as a vertical diagnostic sequence so each
interactive plot has room for zooming, panning, series selection, hover
inspection, annotations, and image export.

The current report includes:

- rolling 72-hour meteogram
- seven-day weather context with the report window highlighted
- weather anomalies and historical percentiles
- solar and wind potential indices
- Hungary electricity load, residual load, renewable generation, and price
- Debrecen weather versus Hungary solar and wind generation
- wind rose, pressure tendency, dew-point spread, and solar diurnal curves
- interactive Skew-T-style model profile with wind and stability diagnostics
- daily explainable weather-regime strip

The model profile is not an observed radiosonde. It is a pressure-level model
diagnostic near Debrecen, with dew point derived from temperature and relative
humidity.

## GitHub Pages

The workflow in `.github/workflows/pages.yml` tests, builds, archives, and
deploys Atlas. Set:

```text
Settings > Pages > Build and deployment > Source > GitHub Actions
```

The workflow runs on pushes, manual dispatches, and an exact three-day cadence.
A daily scheduler is gated by epoch day so the 72-hour rhythm remains consistent
across month boundaries.

The latest static site is deployed from `site/`. Scheduled and manual builds
also commit a complete version under `reports/periods/`. Earlier weekly archives
under `reports/weeks/` remain preserved as historical context.

## Project Structure

```text
configs/                 Debrecen-only reporting and provider settings
data/raw/                Cached API responses
data/processed/          Latest weather, electricity, profile, and metric tables
docs/                    Methods and data-source notes
reports/periods/         Versioned rolling reports, plots, and data
reports/weeks/           Preserved earlier weekly report archives
site/                    Latest GitHub Pages artifact
src/atlas/               Ingestion, analysis, plotting, report, and CLI modules
tests/                   Lightweight offline tests
```

## Interpretation

Weather-based solar and wind indices are normalized to the same three-day
calendar window in the prior-year baseline. They describe meteorological
potential, not metered plant output. The electricity section uses measured
Hungary-wide system data and is labeled separately from Debrecen's local weather.

See [docs/methods.md](docs/methods.md) and
[docs/data_sources.md](docs/data_sources.md) for details.
