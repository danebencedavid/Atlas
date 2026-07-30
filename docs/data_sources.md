# Data Sources

Atlas remains geographically focused on Debrecen. Hungary-wide electricity data
is included because no public Debrecen-level electricity feed provides the
generation and system context needed for this report.

## Implemented Sources

### Open-Meteo Historical Weather API

Purpose:

- hourly weather for the rolling three-day report
- seven-day weather context
- same-calendar-window baselines over prior years

Variables include temperature, dew point, relative humidity, precipitation,
cloud cover, sea-level pressure, 10 m and 100 m wind, wind direction, gusts,
shortwave/direct/diffuse radiation, and sunshine duration.

Official documentation:
[Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)

### Energy-Charts API

Purpose:

- Hungary public electricity generation by type
- load and residual load
- day-ahead price for the HU bidding zone
- cross-border physical-flow context

The API is free, does not require a token for these requests, supports Hungary,
and publishes most returned data under CC BY 4.0 with source attribution. Much
of the European power-system data originates from ENTSO-E.

Official documentation:
[Energy-Charts API](https://api.energy-charts.info/)

### Open-Meteo Historical Forecast API

Purpose:

- model pressure-level temperature and humidity
- pressure-level wind speed and direction
- geopotential height
- interactive Skew-T-style profile near Debrecen

Official documentation:
[Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api)

## Worth Adding Later

### HungaroMet Open Data Portal

HungaroMet is the most relevant governmental source for independent official
Hungarian validation. The best role would be Debrecen-area station and climate
cross-checks after stable station identifiers, formats, and hourly variable
coverage are confirmed.

Portal: [HungaroMet ODP](https://odp.met.hu/)

### NASA POWER Hourly API

NASA POWER would provide an independent solar-radiation cross-check and fallback
for the renewable-weather indices.

Documentation:
[NASA POWER Hourly API](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/)

### NOAA Aviation Weather API

Recent LHDC METAR observations could serve as a live Debrecen International
Airport sanity check. They do not replace the historical hourly baseline.

Documentation:
[NOAA Aviation Weather API](https://aviationweather.gov/data/api/)

## Not Prioritized

ENTSO-E direct API access is not the default because it requires an access token
and XML parsing. Energy-Charts already exposes the required Hungary series
without repository secrets while retaining source attribution.

NOAA CDO/GHCN is valuable for independent climate validation but is better
suited to daily records and requires a token for CDO API access.
