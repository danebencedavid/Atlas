# Atlas — Debrecen weather, placed in context

[Explore the live Atlas](https://danebencedavid.github.io/Atlas/)

Atlas is an observed-weather publication for Debrecen, Hungary. It turns station
measurements, radar, satellite imagery, climate records, and regional weather
analysis into a readable account of what happened, why it happened, and how
unusual it was.

Atlas is designed to answer a few practical questions:

- What was the weather actually like yesterday?
- What shaped the last 72 hours?
- Was it warmer, wetter, windier, or otherwise unusual for the season?
- Were there notable events such as fog, frost, thunderstorms, heavy rain, or a
  frontal passage?
- What did the conditions mean for soil moisture, solar energy, and wind energy?

> Atlas describes completed weather periods. It is not a forecast, warning
> service, or substitute for official safety information.

## Start exploring

### [Latest daily report](https://danebencedavid.github.io/Atlas/report.html)

A concise account of the latest complete day in Debrecen. Start here for the
headline weather story, temperatures, precipitation, wind, cloud, notable
events, energy conditions, and climate context.

### [72-hour meteorological analysis](https://danebencedavid.github.io/Atlas/analysis/)

A deeper reconstruction of the latest three complete days. It follows the
weather from the larger atmospheric setup through surface observations, radar,
satellite, storms, the upper atmosphere, land conditions, and energy impacts.

### [Report archive](https://danebencedavid.github.io/Atlas/archive/)

Browse preserved editions and search the Weather Event Index for past fog,
frost, heat, thunder, heavy rain, snow, and frontal passages.

## How to read Atlas

Every report opens with the observed period, update time, and an integrity
status. A complete edition has passed the required observation-coverage checks;
if essential evidence is missing, Atlas withholds the new edition instead of
presenting an incomplete period as authoritative.

Evidence is labelled consistently throughout the publication:

- **Observed** — measured directly at a weather station or by another in-situ
  instrument.
- **Remote-sensed** — detected by radar, lightning systems, or satellite.
- **Model-derived** — reconstructed from a gridded weather or land analysis.
- **Derived** — calculated transparently from one or more evidence sources.

When Atlas says conditions were above or below normal, the main comparison is
the World Meteorological Organization 1991–2020 standard period. Recent-decade
and full-record comparisons are kept separate so that “normal,” “recent,” and
“rare in the available record” do not become interchangeable claims.

The charts are interactive: hover for exact values, zoom into a period, toggle
series, and use the information control beside a figure for a short guide to
reading it.

## What you will find

- **The weather story** — a plain-language summary connected to the evidence
  that supports it.
- **Surface weather** — temperature, humidity, pressure, wind, cloud, and
  precipitation around Debrecen.
- **Storm and visibility evidence** — radar, lightning, Meteosat imagery, fog,
  low visibility, inversions, frost, heat, snow, and frontal passages.
- **Atmospheric context** — air masses, pressure patterns, jet-stream and
  moisture fields, stability, and storm-environment diagnostics.
- **Climate context** — standard-normal anomalies, recent conditions,
  full-record percentiles, and comparable historical periods.
- **Land and energy** — soil conditions, evaporative demand, water balance,
  reference solar and wind yields, and Hungary-wide electricity context.

The share control on each current report can download a portrait report card or
send the edition to supported apps and social platforms.

## Evidence and limitations

Atlas is deliberately focused on Debrecen. Regional atmospheric fields and
Hungary-wide electricity data provide context, but they are not presented as
local measurements.

Its main evidence comes from:

- HungaroMet station observations, radar, lightning, and Meteosat products;
- Open-Meteo historical weather, land, and pressure-level datasets;
- ERA5 climate references; and
- Energy-Charts electricity-system data for Hungary.

Important distinctions remain visible in the reports:

- model profiles are not observed radiosondes;
- radar accumulation is an estimate and is not adjusted with rain gauges;
- renewable-energy values describe reference-system weather potential, not a
  plant forecast or metered production; and
- detected events are evidence-based classifications, not official warnings.

For formulas, thresholds, provenance, and source links, see the
[methods](docs/methods.md) and [data sources](docs/data_sources.md).

## For contributors

The simplest local preview is the deterministic demo. It uses no external APIs:

```powershell
python -m pip install -e ".[dev]"
atlas --demo
python -m http.server 8000 --directory site
```

Then open `http://127.0.0.1:8000/`.

To build from current public data and run the test suite:

```powershell
atlas --refresh
pytest
```

Useful options include `--period-start YYYY-MM-DD`, `--today YYYY-MM-DD`,
`--config PATH`, and `--skip-analysis-archive`. The legacy `--week-start` option
remains an alias for `--period-start`.

The main project areas are:

```text
configs/          Debrecen-specific settings
docs/             Methods and data provenance
reports/          Preserved daily and 72-hour editions
src/atlas/        Data, analysis, plotting, and publication code
tests/            Offline unit and report-generation tests
site/             Generated static publication
```

GitHub Actions verifies source changes and runs the scheduled publication
pipeline. A successful publication build refreshes the live GitHub Pages site
and preserves the appropriate report editions in the archive.
