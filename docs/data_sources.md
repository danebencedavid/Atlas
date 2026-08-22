# Data Sources

Atlas is geographically focused on Debrecen. Each generated page distinguishes
station observations, radar/lightning detections, model-derived fields,
gridded climate context, and Hungary-wide electricity data.

## HungaroMet Open Data Portal

Implemented products:

- 10-minute station observations for Debrecen Airport, station 64711
- 1 km national composite radar reflectivity in NetCDF
- LINET lightning event records
- Meteosat Second Generation RGB and infrared PNG products

The station is the report's official surface-observation ledger. Radar and
lightning support event reconstruction and retain explicit coverage notes when
the rolling provider archive does not contain every requested frame.

- [10-minute observations](https://odp.met.hu/climate/observations_hungary/10_minutes/)
- [Radar composites](https://odp.met.hu/weather/radar/composite/)
- [Radar NetCDF description](https://odp.met.hu/weather/radar/composite/Description-radar_nc-en.pdf)
- [Lightning data](https://odp.met.hu/weather/lightning/)
- [Meteosat products](https://odp.met.hu/weather/satellite/MSG/)
- [Meteosat product descriptions](https://odp.met.hu/weather/satellite/MSG/Description_MSG-en.pdf)
- [HungaroMet Open Data Portal terms](https://odp.met.hu/ODP_General_Term_of_Use.pdf)

## Open-Meteo Historical Weather API

Used for the continuous hourly report, seven-day diary, best-match 90-day land
context, fixed-ERA5 10-year and 1991-2020 same-calendar comparisons,
full-record ERA5 percentiles, and the 15-year daily analog archive. Variables
include temperature, dew point, humidity, precipitation/snow, cloud, pressure,
wind, radiation, sunshine, VPD, ET0, soil temperature, and soil moisture.

[Official documentation](https://open-meteo.com/en/docs/historical-weather-api)

## Open-Meteo Historical Forecast API

Used for pressure-level profiles, parcel and boundary-layer time series, and
the Central European synoptic animation. Synoptic inputs include 300/500/700/
850 hPa wind, temperature, humidity, vertical velocity, and geopotential height.
Vorticity, advection, theta-e and frontogenesis are derived locally. These are
model analyses, not observed soundings or manually analysed maps.

[Official documentation](https://open-meteo.com/en/docs/historical-forecast-api)

## Attribution and licence

Open-Meteo data is licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and requires credit, a
link to the licence, and an indication of whether changes were made.

Atlas modifies the data by aggregating values, combining sources, and deriving
diagnostics. Generated pages and figures carry the required attribution and
licence link.

HungaroMet is credited visibly as “Source: Hungarian Meteorological Service
(HungaroMet)” on every page and embedded figure, as well as beside individual
HungaroMet products. The English Open Data Portal terms currently state that
changes require prior written consent. Atlas has requested that consent; until a
written answer is received, attribution is complete but permission for the
project's derived HungaroMet products remains an external publication risk.

ERA5-derived climate material carries the notice “Contains modified Copernicus
Climate Change Service information 2026” and the required disclaimer that
neither the European Commission nor ECMWF is responsible for its use. See the
[Copernicus licence](https://cds.climate.copernicus.eu/licences/licence-to-use-copernicus-products).

## Energy-Charts API

Used for Hungary-wide generation by type, load, residual load, day-ahead price,
and cross-border physical flow. The public API requires no token; much of the
underlying European power-system data originates from ENTSO-E. National values
are never labelled as Debrecen measurements.

[Official API](https://api.energy-charts.info/)

Generated pages and figures credit Energy-Charts and Fraunhofer ISE wherever
the Hungary-wide electricity context is published. No licence claim beyond the
provider's published API terms is made.

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
