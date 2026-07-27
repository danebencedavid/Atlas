# Atlas

Atlas is a weekly automated GitHub Pages dashboard for Debrecen, Hungary. It
combines a weather anomaly atlas, a weather regime diary, and renewable-energy
weather indices.

Core question:

> What kind of weather week did Debrecen / Hungary just have, how unusual was it
> compared with normal, and what did it imply for solar and wind energy
> potential?

## What It Builds

The pipeline:

1. Finds the last complete Monday-Sunday week in Europe/Budapest.
2. Fetches hourly historical weather data from Open-Meteo.
3. Fetches the same calendar-week window for prior years as a baseline.
4. Computes temperature, precipitation, wind, pressure, cloud, and solar
   anomalies.
5. Computes solar, wind, and combined renewable-weather scores.
6. Classifies the week into a transparent weather regime.
7. Renders static meteorological figures.
8. Builds `site/index.html` for GitHub Pages.

## Included MVP Visuals

- Interactive weekly meteogram
- Interactive wind rose
- Interactive pressure tendency plot
- Interactive temperature-dew point spread plot
- Interactive solar radiation diurnal curves
- Interactive weather anomaly bars
- Interactive solar-wind energy quadrant
- Interactive daily regime classification strip

The dashboard uses Plotly HTML figures, so readers can zoom, pan, hover, toggle
series, box-select, and export views directly in the browser.

## Local Use

```powershell
python -m pip install -e ".[dev]"
atlas
```

The generated dashboard is written to `site/index.html`. Generated raw data,
processed CSV files, and figures are ignored locally because the GitHub Actions
workflow regenerates them.

To build a specific week:

```powershell
atlas --week-start 2026-07-20
```

## GitHub Pages Automation

The workflow in `.github/workflows/pages.yml` runs:

- on pushes to `main` or `master`
- weekly on Monday morning
- manually through `workflow_dispatch`

It installs the package, runs tests, builds the dashboard, uploads the static
`site/` artifact, and deploys it to GitHub Pages.

For unattended weekly runs, Atlas checks that the selected local Monday-Sunday
week has complete hourly coverage. If the archive API has not yet published a
complete just-ended week, Atlas steps back to the latest complete week within
the configured lag window instead of publishing a partial dashboard.

## Data Sources

The MVP uses the Open-Meteo Historical Weather API. NASA POWER is documented as
a later optional solar-focused fallback. See `docs/data_sources.md`.

## Interpretation

Atlas is descriptive, diagnostic, climatological, and energy-oriented. It is
not a forecast calibration project.
