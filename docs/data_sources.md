# Data Sources

Atlas is Debrecen-only. The data-source strategy is therefore judged by whether
it improves a weekly local diagnostic dashboard for Debrecen, not whether it
supports wider Hungary coverage.

## Current MVP Source

### Open-Meteo Historical Weather API

Status: implemented.

Purpose:

- hourly weather variables for the latest complete local week
- same calendar-week baseline windows over prior years
- no secrets required
- reliable GitHub Actions fit

Variables used:

- temperature_2m
- dew_point_2m
- relative_humidity_2m
- precipitation
- cloud_cover
- pressure_msl
- wind_speed_10m
- wind_speed_100m
- wind_direction_10m
- wind_gusts_10m
- shortwave_radiation
- direct_radiation
- diffuse_radiation
- sunshine_duration

## Government APIs Worth Adding

### HungaroMet ODP

Status: worth adding.

HungaroMet is the most relevant governmental source for this project because it
is the Hungarian national meteorological open data portal. It provides official
Hungarian observation, climate, radar, and model datasets through downloadable
open-data paths at `odp.met.hu`.

Best Atlas use:

- official Debrecen-area station/climate cross-checks
- official Hungarian climate baseline context
- possible station metadata and recent observation validation

Implementation note:

- Treat this as a supplemental validator first, not as a replacement for the
  current hourly Open-Meteo pipeline.
- Add it only after identifying the best Debrecen station IDs and variable
  coverage in the ODP station metadata.

### NASA POWER Hourly API

Status: worth adding.

NASA POWER is especially useful for Atlas because the project has an explicit
renewable-energy weather component. The hourly API supports solar and
meteorological parameters in JSON and CSV, and can return UTC time series.

Best Atlas use:

- solar radiation cross-check
- renewable-energy weather index fallback
- sanity check for shortwave radiation anomalies

Implementation note:

- Use POWER as a solar/energy fallback, not as the primary local weather source.
- Keep requests small because the hourly API limits the number of parameters per
  request.

### NOAA Aviation Weather API

Status: useful but secondary.

The NOAA Aviation Weather Center API provides worldwide METAR data, including
current and recent terminal observations, with JSON and CSV output. Debrecen
International Airport is LHDC.

Best Atlas use:

- live/current LHDC METAR sanity check
- optional "latest aviation observation" note on the dashboard
- verifying that the report location remains grounded in a real station context

Implementation note:

- It covers only recent aviation observations, not the full historical weekly
  baseline Atlas needs.

## Government APIs Not Prioritized

### NOAA CDO / GHCN

Status: not a near-term priority.

NOAA Climate Data Online and GHCN are valuable climate archives, but CDO API
access requires a token and is more natural for daily climate checks than the
hourly weekly report. It may be useful later for independent daily temperature
or precipitation validation.

## Not Governmental But Still Useful

### Open-Meteo

Open-Meteo remains the best MVP backbone because it is no-secret, hourly,
static-site friendly, and already exposes the weather and radiation variables
needed by Atlas.
