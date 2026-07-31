# Data Sources

Atlas is geographically focused on Debrecen. Each generated page distinguishes
station observations, radar/lightning detections, model-derived fields,
gridded climate context, and Hungary-wide electricity data.

## HungaroMet Open Data Portal

Implemented products:

- 10-minute station observations for Debrecen Airport, station 64711
- 1 km national composite radar reflectivity in NetCDF
- LINET lightning event records

The station is the report's official surface-observation ledger. Radar and
lightning support event reconstruction and retain explicit coverage notes when
the rolling provider archive does not contain every requested frame.

- [10-minute observations](https://odp.met.hu/climate/observations_hungary/10_minutes/)
- [Radar composites](https://odp.met.hu/weather/radar/composite/)
- [Radar NetCDF description](https://odp.met.hu/weather/radar/composite/Description-radar_nc-en.pdf)
- [Lightning data](https://odp.met.hu/weather/lightning/)

## Open-Meteo Historical Weather API

Used for the continuous hourly report, seven-day diary, 10-year same-calendar
baseline, and 15-year daily analog archive. Variables include temperature, dew
point, humidity, precipitation, cloud, pressure, 10 m/100 m wind, gusts,
shortwave/direct/diffuse radiation, and sunshine duration.

[Official documentation](https://open-meteo.com/en/docs/historical-weather-api)

## Open-Meteo Historical Forecast API

Used for pressure-level profiles, parcel and boundary-layer time series, and
the Central European synoptic animation. These are model analyses near
Debrecen, not observed soundings.

[Official documentation](https://open-meteo.com/en/docs/historical-forecast-api)

## Energy-Charts API

Used for Hungary-wide generation by type, load, residual load, day-ahead price,
and cross-border physical flow. The public API requires no token; much of the
underlying European power-system data originates from ENTSO-E. National values
are never labelled as Debrecen measurements.

[Official API](https://api.energy-charts.info/)

## Scientific Libraries

- [MetPy](https://unidata.github.io/MetPy/latest/) supplies parcel,
  thermodynamic, and sounding calculations.
- [pvlib-python](https://pvlib-python.readthedocs.io/) supplies solar position,
  transposition, and module-temperature calculations.
- [Plotly Python](https://plotly.com/python/) produces self-contained
  interactive figures for GitHub Pages.

## Useful Independent Checks

NASA POWER can provide an independent radiation cross-check, and NOAA IGRA can
provide radiosonde context from the nearest available upper-air stations. They
are not blended into the current products because neither is a superior direct
observation of the exact Debrecen atmospheric column.

- [NASA POWER hourly API](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/)
- [NOAA Integrated Global Radiosonde Archive](https://www.ncei.noaa.gov/products/weather-balloon/integrated-global-radiosonde-archive)

Direct ENTSO-E ingestion is not the default because it requires an access token
and XML processing. Energy-Charts supplies the required Hungary system context
without repository secrets while retaining source attribution.
