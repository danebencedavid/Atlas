# Data Sources

Atlas is designed around public APIs that do not require secrets.

## Open-Meteo Historical Weather API

The MVP fetches hourly data from the Open-Meteo Historical Weather API:

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

Requests use UTC internally. The generated report displays the local calendar
week for Europe/Budapest.

## NASA POWER

NASA POWER is a good later fallback or cross-check, especially for solar-energy
variables. It is not required for the MVP pipeline.
