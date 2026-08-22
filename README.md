# Atlas: Debrecen Meteorological Atlas

Atlas builds two linked Debrecen publications from one deterministic weather
pipeline: a public report for the latest complete local day and an expert
meteorological analysis covering the latest 72 complete local hours. It uses
official surface observations, radar, lightning, Meteosat imagery, gridded
weather and land analyses, pressure-level model fields, climate references,
historical analogs, and electricity-system data.

The project remains deliberately focused on Debrecen. Hungary-wide electricity
and Central European synoptic fields provide context; they are not presented as
local observations.

The main pipeline uses real public APIs:

- HungaroMet Open Data Portal for Debrecen Airport station observations,
  Hungarian radar composites, LINET lightning, and Meteosat products
- Open-Meteo Historical Weather API for continuous hourly weather, fixed ERA5
  climate references, and best-match rolling land fields
- Open-Meteo Historical Forecast API for pressure-level profiles and Central
  European synoptic fields
- Energy-Charts API for Hungarian load, generation, residual load,
  cross-border flow, and day-ahead price

No API key or repository secret is required.

The first uncached run bootstraps immutable annual ERA5 reference files. GitHub
Actions preserves that progress even when a provider throttles a build; later
daily runs restore the completed years and normally fetch only rolling inputs.

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
data/processed/{standard_normal,full_record}_metrics.csv
data/processed/weather_phenomena.csv
data/processed/land_surface_{hourly,daily}.csv
data/processed/satellite_manifest.csv
reports/daily/YYYY-MM-DD/                     lightweight daily public edition
reports/periods/YYYY-MM-DD_YYYY-MM-DD/         versioned complete report
site/index.html                                project overview and publication guide
site/report.html                               latest daily public report
site/analysis/                                 latest 72-hour expert analysis
site/archive/                                  reports plus searchable weather-event index
site/archive/data/weather_event_index.json     machine-readable de-duplicated events
```

## Main Commands

```powershell
atlas
atlas --refresh
atlas --period-start 2026-07-28
atlas --today 2026-07-31
atlas --config configs/atlas.yml --refresh
atlas --refresh --skip-analysis-archive
pytest
```

`--week-start` remains as a compatibility alias for `--period-start`.

## The Atlas

The landing page is a compact project guide based on this README: it states the
research question, evidence hierarchy, scientific scope, update cadence, and
links to the current publications and archive. The reporting area is organized
as two meteorological publications rather than a plot wall. A persistent switch
moves between them.

The **Public Report** updates daily:

- **Overview** summarizes yesterday in plain language.
- **Weather**, **Events**, and **Energy** retain only the diagnostics needed to
  understand the day.
- **Climate Context** compares yesterday with the preceding week, 1991-2020,
  the recent decade, and the full ERA5 record.

The **Meteorological Analysis** covers 72 hours:

- **Overview** gives the regime, concise situation assessment, physical energy
  yields, historical analog, and an annotated 72-hour meteogram.
- **Weather Story** turns the report evidence into an interactive, deterministic
  chain from atmospheric setup through observed weather to land and energy impacts.
- **Surface & Synoptic** puts station observations first, then offers
  selectable jet, vorticity, moisture/ascent, theta-e, and frontogenesis layers.
- **Storms & Satellite** synchronizes Meteosat imagery with radar and lightning
  and presents an objective phenomenon evidence ledger.
- **Upper Air & Dynamics** combines a model Skew-T, hodograph, parcel and boundary-layer
  ledger, and a modified Hovmoller time-pressure curtain.
- **Climate & Analogs** separates the WMO standard normal, recent decade, and
  full-record percentile before showing analogs and recent evolution.
- **Land Surface & Energy** adds soil, VPD, ET0, and 7/30/90-day water balance
  before physical renewable yields and measured Hungary-wide conditions.
- **Methods & Evidence** records provenance, limitations, confidence, and direct
  downloads of every generated data product.

The **Report Archive** includes a Weather Event Index. One search field covers
saved report dates and the event ledgers from preserved 72-hour editions. Event
detections repeated by overlapping rolling windows are de-duplicated, and each
result links back to the edition that carries its evidence.

All analytical plots are interactive Plotly documents with zoom, pan, hover,
series selection, animation where appropriate, and image export. Each plot has
a compact information control explaining how a meteorologist should read it.

## Scientific Scope

Atlas includes:

- 10-minute HungaroMet observations from station 64711, Debrecen Airport
- sampled 1 km Hungarian radar composite replay and a transparent Z-R
  accumulation proxy
- LINET lightning events within 150 km of Debrecen
- sampled Airmass, Natural Colour, Night Microphysics, Fog RGB, and infrared
  Meteosat products synchronized with radar and lightning
- explainable local frontal-passage detection with diurnal false-positive
  suppression
- an observed-first objective ledger for fog, low visibility, inversions,
  frost, heat, thunder, heavy rain, gusts, snow, and frontal passages
- MetPy surface-parcel CAPE, CIN, LCL, LFC, EL, precipitable water, wet-bulb
  zero, freezing level, boundary-layer height, and ventilation diagnostics
- seasonal historical analog ranking over the prior 15 years
- selectable animated 300 hPa jet, 500 hPa vorticity, 700 hPa humidity/vertical
  motion, and 850 hPa theta-e, thermal-advection, and frontogenesis diagnostics
- WMO 1991-2020 standard-normal anomalies, a separate recent-decade comparison,
  and same-calendar percentile ranks across ERA5 from 1990
- 90-day soil-temperature, soil-moisture, VPD, ET0, and water-balance analysis
- pvlib plane-of-array PV modeling and an air-density-corrected turbine model
- a separate normalized climatological solar-wind weather index
- an evidence-driven Weather Story graph whose nodes and links are regenerated
  from each report rather than authored as a fixed narrative

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

The workflow runs daily at 11:00 UTC, on pushes, and by manual dispatch. Every
scheduled build commits a lightweight public edition under `reports/daily/`.
A full self-contained expert edition is committed under `reports/periods/` on a
true three-day cadence. The latest versions of both are deployed from `site/`.
The generated **Archive** page publishes every saved daily, 72-hour, and legacy
weekly edition with date filtering and direct links to its preserved pages.
Archived HTML is presented in the current Atlas shell while its original data,
figures, dates, and deterministic interpretation remain unchanged.

## Project Structure

```text
configs/                 Debrecen-only provider and scientific settings
data/raw/                Cached API responses, ignored locally
data/processed/          Latest analysis tables and arrays, ignored locally
docs/                    Data provenance and methods
reports/periods/         Versioned rolling reports committed by CI
reports/daily/           Lightweight public daily editions committed by CI
reports/weeks/           Preserved historical weekly editions
site/index.html          Project home and publication guide
site/report.html         Latest daily public overview
site/analysis/           Latest rolling expert analysis
site/archive/            Saved reports and searchable weather-event evidence
src/atlas/               Ingestion, diagnostics, plotting, site, and CLI code
tests/                   Offline unit and report smoke tests
```

See [docs/methods.md](docs/methods.md) and
[docs/data_sources.md](docs/data_sources.md) for formulas, thresholds, source
links, and limitations.
