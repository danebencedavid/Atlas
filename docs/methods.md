# Methods

Atlas answers a Debrecen-only descriptive question: what kind of weather
occurred during the latest three complete local days, how unusual was it, and
what did it imply for renewable energy and electricity conditions?

## Reporting Window

The default report ends at local midnight before the run date and covers the
previous three complete calendar days in `Europe/Budapest`. API timestamps are
handled internally in UTC and filtered to exact local-time boundaries, including
daylight-saving transitions.

The automated workflow runs daily but uses an epoch-day gate to publish every
three days. Push and manual runs always build.

Atlas validates hourly completeness before publishing. If the newest weather
archive is incomplete, it steps backward one day at a time within the configured
lag limit and uses the latest complete 72-hour period.

## Seven-Day Context

The primary anomaly calculations use only the three-day reporting period. A
separate seven-day plot shows daily temperature range, precipitation, radiation,
and 100 m wind, with the current report highlighted. This preserves a weekly
weather-diary perspective without diluting the rolling report.

## Versioned Reports

Each build creates the latest static site in `site/`. Scheduled and manual CI
builds also save a self-contained archive in:

```text
reports/periods/YYYY-MM-DD_YYYY-MM-DD/
```

The archive contains the dashboard, interactive Plotly figures, processed CSV
tables, and summary JSON. Existing `reports/weeks/` artifacts remain untouched.

## Baseline And Anomalies

The baseline maps the three-day calendar window into each configured prior year.
The default is 10 years, with at least five complete years required. Atlas
compares current aggregate values with the distribution of those prior-year
period aggregates.

Anomalies cover mean temperature, total precipitation, mean 100 m wind where
available, mean sea-level pressure, mean cloud cover, and total shortwave
radiation. Percentiles and standardized anomalies are both reported.

## Renewable Weather Indices

The solar index uses shortwave radiation relative to the baseline and applies a
penalty when cloud cover is above normal.

The wind index uses a cubic wind-speed proxy relative to baseline because
available wind power is approximately proportional to wind speed cubed within
the operating range. Calm periods receive an additional penalty.

The combined score is the mean of the solar and wind indices. Scores are clipped
to 0-100 for public readability and represent weather potential, not plant
metering or a power forecast.

## Electricity Metrics

Energy-Charts supplies Hungary-wide public electricity data. Atlas ingests public
generation by type, system load, residual load, day-ahead price, and cross-border
physical flow where available.

Power values are integrated over their observed time intervals to calculate
period energy in MWh. Weather-electricity scatter plots align national
electricity series with hourly Debrecen radiation and wind. These relationships
are diagnostic and should not be interpreted as causal estimates for the entire
Hungarian fleet.

If Energy-Charts is temporarily unavailable, the weather report still builds and
the electricity panels show an explicit unavailable state.

## Atmospheric Profile

The Skew-T-style panel uses pressure-level fields from the Open-Meteo Historical
Forecast API near Debrecen. It selects the model profile closest to 12 UTC on the
final report day.

Temperature and dew point are drawn against logarithmic pressure on a skewed
temperature coordinate. A separate wind profile shows speed and direction.
Displayed diagnostics include K index, total-totals index, 850-500 hPa lapse
rate, and freezing-level height when calculable.

The profile is model-derived, not an observed radiosonde. Dew point is calculated
from model temperature and relative humidity.

## Regime Classification

The regime classifier is intentionally transparent. It uses anomaly signals and
simple thresholds for radiation, cloudiness, precipitation, wind, pressure
range, heat demand, and frost-prone hours.

Candidate labels:

- Sunny high-pressure period
- Cloudy stagnant period
- Wet frontal period
- Windy frontal period
- Heat-stress period
- Cold/frost-prone period
- Mixed transition period

This is not a black-box model and is not a forecast-calibration system.
