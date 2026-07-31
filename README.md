# Atlas: Debrecen Meteorological Atlas

Atlas builds an expert-facing, three-day meteorological situation report for
Debrecen, Hungary. It reconstructs the latest 72 complete local hours from
official surface observations, radar, lightning, gridded weather analyses,
pressure-level model fields, climate analogs, and electricity-system data.

The project remains deliberately focused on Debrecen. Hungary-wide electricity
and Central European synoptic fields provide context; they are not presented as
local observations.

The main pipeline uses real public APIs:

- HungaroMet Open Data Portal for Debrecen Airport station observations,
  Hungarian radar composites, and LINET lightning data
- Open-Meteo Historical Weather API for continuous hourly weather and the
  prior-year climatological baseline
- Open-Meteo Historical Forecast API for pressure-level profiles and Central
  European synoptic fields
- Energy-Charts API for Hungarian load, generation, residual load,
  cross-border flow, and day-ahead price

No API key or repository secret is required.

## Research Question

What weather situation did Debrecen experience during the last three complete
days, how unusual was it for the season, how did the atmospheric column and
nearby convective environment evolve, and what did the weather imply for solar
and wind energy potential?

Atlas is descriptive, diagnostic, climatological, and energy-oriented. It is
not a forecast-calibration project or an operational warning service.

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
data/raw/                                      cached provider responses
data/processed/current_hourly.csv             rolling weather analysis
data/processed/hungaromet_station_observations.csv
data/processed/radar_{timeline,accumulation}.*
data/processed/lightning_events.csv
data/processed/frontal_passages.csv
data/processed/historical_analogs.csv
data/processed/model_profile*.csv
data/processed/synoptic_fields.npz
data/processed/physical_energy.csv
reports/periods/YYYY-MM-DD_YYYY-MM-DD/         versioned complete report
site/                                          latest GitHub Pages artifact
```

## Main Commands

```powershell
atlas
atlas --refresh
atlas --period-start 2026-07-28
atlas --today 2026-07-31
atlas --config configs/atlas.yml --refresh
pytest
```

`--week-start` remains as a compatibility alias for `--period-start`.

## The Atlas

The site is organized as a meteorological publication rather than a plot wall:

- **Overview** gives the regime, concise situation assessment, physical energy
  yields, historical analog, and an annotated 72-hour meteogram.
- **Weather** puts HungaroMet station observations first, then explains the
  synoptic evolution, wind regime, and pressure tendency.
- **Storms** forms an event diary from radar replay, reflectivity-derived
  accumulation, LINET lightning, and objective passage candidates.
- **Upper Air** combines a model Skew-T, hodograph, parcel and boundary-layer
  ledger, and a modified Hovmoller time-pressure curtain.
- **Climate** places the period among its closest 15-year seasonal analogs,
  prior-week evolution, anomalies, regimes, and solar climatology.
- **Energy** translates weather into a reference PV yield and generic turbine
  capacity factor before showing measured Hungary-wide system conditions.
- **Methods** records provenance, limitations, baseline statistics, and direct
  downloads of every generated data product.

All analytical plots are interactive Plotly documents with zoom, pan, hover,
series selection, animation where appropriate, and image export. Each plot has
a compact information control explaining how a meteorologist should read it.

## Scientific Scope

Atlas includes:

- 10-minute HungaroMet observations from station 64711, Debrecen Airport
- sampled 1 km Hungarian radar composite replay and a transparent Z-R
  accumulation proxy
- LINET lightning events within 150 km of Debrecen
- explainable local frontal-passage detection with diurnal false-positive
  suppression
- MetPy surface-parcel CAPE, CIN, LCL, LFC, EL, precipitable water, wet-bulb
  zero, freezing level, boundary-layer height, and ventilation diagnostics
- seasonal historical analog ranking over the prior 15 years
- animated sea-level pressure, 500 hPa height, 850 hPa temperature, and wind
- pvlib plane-of-array PV modeling and an air-density-corrected turbine model
- a separate normalized climatological solar-wind weather index

Model profiles are not observed radiosondes. Radar accumulation is not
gauge-adjusted. Physical energy outputs are reference-system weather yields,
not plant forecasts or metered generation. These distinctions are repeated in
the generated report wherever they matter.

## GitHub Pages

The workflow in `.github/workflows/pages.yml` tests, builds, archives, and
deploys Atlas. In GitHub, set:

```text
Settings > Pages > Build and deployment > Source > GitHub Actions
```

The workflow runs on pushes, manual dispatches, and a true three-day cadence.
Scheduled builds commit a self-contained report under `reports/periods/`; the
latest site is deployed from `site/`. Existing weekly archives remain available
as longer-context historical editions.

## Project Structure

```text
configs/                 Debrecen-only provider and scientific settings
data/raw/                Cached API responses, ignored locally
data/processed/          Latest analysis tables and arrays, ignored locally
docs/                    Data provenance and methods
reports/periods/         Versioned rolling reports committed by CI
reports/weeks/           Preserved historical weekly editions
site/                    Latest generated Pages artifact
src/atlas/               Ingestion, diagnostics, plotting, site, and CLI code
tests/                   Offline unit and report smoke tests
```

See [docs/methods.md](docs/methods.md) and
[docs/data_sources.md](docs/data_sources.md) for formulas, thresholds, source
links, and limitations.
