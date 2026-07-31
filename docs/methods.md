# Methods

Atlas answers a Debrecen-only diagnostic question: what weather occurred during
the latest three complete local days, how unusual was it, what processes shaped
it, and what did it imply for renewable energy?

## Reporting Window And Quality Control

The report ends at local midnight before the run date and covers three complete
calendar days in `Europe/Budapest`. Provider timestamps are converted to UTC
internally and clipped to exact local boundaries, including daylight-saving
transitions. The publication requires at least 95% hourly coverage from the
continuous Open-Meteo series and steps backward within a seven-day lag limit if
the newest archive is incomplete.

A separate seven-day diary preserves the transition into the active period.
Every generated edition is copied to
`reports/periods/YYYY-MM-DD_YYYY-MM-DD/` with its figures and data.

## Observation Ledger

HungaroMet station 64711 at Debrecen Airport is the primary surface observation
point. Ten-minute temperature, relative humidity, precipitation, visibility,
sea-level pressure, wind, direction, and gust records are filtered to the local
report window and aggregated hourly for comparison. Dew point is calculated
with the Magnus relation. Hourly wind direction is a speed-weighted circular
mean, not an arithmetic mean.

The Open-Meteo grid remains the continuous series used for climatological
metrics. Station-versus-grid differences are displayed rather than blended.

## Radar And Lightning

The radar panel uses HungaroMet's 1 km national composite reflectivity. Atlas
decodes the packed field as `dBZ = unsigned_value / 2 - 32`, samples source
frames every 30 minutes, and uses hourly frames for browser replay. The display
grid is sampled to 3 km to keep the static Pages artifact responsive; rainfall
is calculated before display sampling.

The accumulation proxy applies the Marshall-Palmer relation
`Z = 200 R^1.6` to each available radar frame. It is not gauge-adjusted and may
be biased by bright band, attenuation, anomalous propagation, beam geometry, or
missing frames. Every report states the exact source-frame coverage.

The lightning diary reads HungaroMet LINET records, filters great-circle
distance to 150 km from Debrecen, and retains event time, polarity/current,
type, location quality, and range. It is an event catalogue, not a flash-area
product.

## Objective Frontal Passages

Station observations are aggregated hourly. Atlas evaluates three-hour changes
in pressure, temperature, dew point, wind speed and direction, plus three-hour
precipitation and gusts. Candidate hours require at least three signals and a
synoptic anchor: a pressure change of at least 2.5 hPa, precipitation of at
least 0.5 mm, or a gust of at least 10 m/s. Nearby candidates are consolidated
within six hours.

Temperature sign separates probable cold- and warm-front signatures; ambiguous
events are labelled frontal trough or wind-shift line. These are reproducible
local annotations, not manually analysed fronts or warnings.

## Baseline, Anomalies, And Analogs

The anomaly baseline maps the same three-day calendar window into each of the
previous 10 years and requires at least five complete years. It reports raw,
standardized, and percentile anomalies for temperature, precipitation, 100 m
wind, pressure, cloud, and shortwave radiation.

The analog engine searches rolling three-day periods from the previous 15
years within a plus/minus 45-day seasonal window. It standardizes mean
temperature, precipitation, wind, shortwave energy, cloud cover, and pressure;
applies transparent feature weights; ranks Euclidean distance; and excludes
overlapping winners. Similarity is `100 exp(-0.5 d^2)`. It measures weather-state
likeness, not downstream impacts or forecast skill.

## Atmospheric Column

Open-Meteo Historical Forecast pressure levels provide temperature, humidity,
wind, and geopotential height near Debrecen. The selected Skew-T profile is
closest to 12 UTC on the last report day; the full series feeds the time-pressure
curtain and boundary-layer panel.

MetPy calculates a surface parcel profile, CAPE, CIN, LCL, LFC, equilibrium
level, precipitable water, and wet-bulb zero where the available model levels
support them. Model CAPE/CIN, freezing level, boundary-layer height, total-column
water, 2 m wet-bulb temperature, and ventilation index provide time context.
K index, total totals, 850-500 hPa lapse rate, and 0-1/0-3/0-6 km bulk shear are
also reported.

These are model-derived diagnostics. Coarse pressure levels can miss shallow
inversions and underestimate extreme parcel quantities; no radiosonde is
claimed.

## Synoptic Evolution

The Central European animation samples a 1-degree grid every six hours. It
combines sea-level pressure, 500 hPa geopotential height, 850 hPa temperature,
and 850 hPa wind. The panel is for circulation and air-mass interpretation, not
mesoscale warning decisions.

## Renewable Energy

The public solar index compares shortwave radiation with the calendar-window
baseline and penalizes excess cloud. The wind index compares cubic wind-speed
potential and penalizes calm conditions. Both are clipped to 0-100 and are
climatological communication indices.

The physical PV model uses pvlib solar position, direct/diffuse decomposition,
fixed 35-degree south-facing plane-of-array irradiance, Faiman cell temperature,
a -0.4%/C temperature coefficient, and a 96% balance-of-system factor. Output is
kWh per installed kWp.

The physical wind model uses 100 m wind, moist-air density from temperature,
humidity and pressure, and a generic cubic turbine curve with 3/12/25 m/s
cut-in/rated/cut-out speeds. It reports reference full-load hours, capacity
factor, and atmospheric wind power density. It does not represent a named
turbine, wake losses, curtailment, terrain flow, or metered production.

## Electricity Context

Energy-Charts provides Hungary-wide generation, load, residual load, price, and
cross-border flow. Power is integrated over observed intervals for energy
totals. Local weather versus national power relationships are diagnostic only;
they do not establish causality or plant-level response.

## Regimes

The regime classifier remains rule-based and inspectable. It selects among
sunny high-pressure, cloudy stagnant, wet frontal, windy frontal, heat-stress,
cold/frost-prone, and mixed transition periods from anomaly and event signals.
It is not a black-box classifier or forecast-calibration system.
