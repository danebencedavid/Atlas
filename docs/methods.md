# Methods

Atlas answers a Debrecen-only descriptive question: what kind of weather week
just happened, how unusual was it compared with normal, and what did it imply
for solar and wind energy potential?

## Week Window

The default run uses the last complete Monday-Sunday week in the configured
local timezone. For Debrecen, that is Europe/Budapest.

Atlas fetches the UTC span needed to cover that local calendar week, then
filters the time series to the exact local-week bounds. This avoids mixing a
UTC Monday-Sunday window with a Hungary local Monday-Sunday report.

For automated runs, Atlas validates hourly completeness before publishing. If
the most recent week is incomplete because an archive feed is lagging, it checks
older weeks within the configured lag window and uses the latest complete one.

## Versioned Reports

Each build creates the latest static site in `site/` and a versioned weekly
archive in `reports/weeks/YYYY-MM-DD_YYYY-MM-DD/`. The archive contains:

- `index.html`
- interactive Plotly figures in `assets/`
- report data in `data/`

The GitHub Actions workflow commits `reports/weeks/` back to the repository
when a new weekly archive is generated.

## Baseline

The baseline uses the same calendar dates over the configured number of prior
years. The default is 10 years. Weekly anomaly values compare the current week
with the mean of those prior weekly aggregates.

## Energy Indices

The solar index is based on weekly shortwave radiation relative to baseline,
with an added penalty for cloudier-than-normal weeks.

The wind index uses a cubic wind-speed proxy relative to baseline, since wind
power scales approximately with the cube of wind speed. Calm weeks receive an
additional penalty.

The combined renewable weather score is the average of the solar and wind
indices. Values are clipped to 0-100 for public readability.

## Regime Classification

The first Atlas regime classifier is intentionally transparent. It uses weekly
anomaly signals and simple thresholds for radiation, cloudiness, precipitation,
wind, pressure range, heat demand, and frost-prone hours.

Candidate labels:

- Sunny high-pressure week
- Cloudy stagnant week
- Wet frontal week
- Windy frontal week
- Heat-stress week
- Cold/frost-prone week
- Mixed transition week

This is not a black-box model and is not a forecast calibration system.
