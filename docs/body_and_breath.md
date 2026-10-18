# Body & Breath

Implementation specification for a human-centred, retrospective account of
outdoor thermal stress and the air measured over Debrecen.

**Status:** proposed, researched, ready for phased implementation  
**Scope:** outdoor environmental conditions, not personal medical advice  
**Primary home:** 72-Hour Analysis, with a compact Daily Report summary  
**Last researched:** 2026-08-22

## 1. Product decision

Body & Breath should make two normally separated environmental stories readable
together:

- **Body** describes the thermal environment through the Universal Thermal
  Climate Index (UTCI), mean radiant temperature, air temperature, humidity,
  wind, solar exposure, and overnight recovery.
- **Breath** describes station-measured PM2.5, PM10, nitrogen dioxide, ozone,
  and supporting pollutants, with separately labelled CAMS model context and
  optional pollen.

The most important design decision is what the feature must *not* do. It must
not collapse heat and air pollution into a single health score. The science,
time scales, exposure pathways, and individual vulnerability are different.
Atlas can show co-occurrence and explain environmental conditions; it cannot
infer an individual's dose, symptoms, safety, or medical risk.

The feature should therefore use two synchronized lanes and one compound-view
matrix, while preserving separate values, categories, sources, uncertainty, and
coverage.

### Recommended launch form

1. Launch **Breath Observed** first with official Debrecen monitoring data,
   provided a stable EEA download integration passes a live data audit.
2. Add **Breath Model Context** from CAMS through Open-Meteo as a separately
   labelled, no-secret source. It fills spatial and pollutant context, never an
   observation gap.
3. Bootstrap **Body Reanalysis** from ERA5-HEAT UTCI and mean radiant
   temperature. Its data lag is acceptable for archive/climate views, but a
   missing latest day must not block Atlas.
4. Add a current **reference-shade UTCI estimate** only after its independent
   calculation and bounds are validated. Never label it ERA5-HEAT or use it to
   silently replace delayed ERA5-HEAT.
5. Add modeled pollen last, seasonally and with prominent model/forecast
   wording. Atlas remains an observed retrospective publication, so future
   pollen values do not belong in the report.

## 2. Reader questions

A visitor should be able to answer:

- When did outdoor heat or cold stress peak during the last 72 complete hours?
- Was radiant load making the environment feel substantially warmer than air
  temperature alone suggested?
- Did the night provide thermal recovery, or did stress remain elevated?
- What did each official Debrecen monitor measure, for which pollutant, and with
  what completeness/validation state?
- Which pollutant determined the hourly European Air Quality Index category?
- Did the urban-traffic and urban-background stations tell different stories?
- Were pollution episodes aligned with weak ventilation, a shallow boundary
  layer, an inversion, frontal change, or strong solar/ozone conditions?
- When heat stress and degraded air quality overlapped, how long did the overlap
  last? Were both inputs actually available?
- Which values are observed, which are model-derived, and which are Atlas
  calculations?

The page should help a reader reconstruct environmental exposure opportunity,
not decide whether a particular person should exercise, work, travel, or change
medication.

## 3. Safety, language, and non-goals

### Required page statement

> Body & Breath describes outdoor environmental conditions in Debrecen. It is
> not medical advice, a personal exposure estimate, or an official air-quality
> or heat warning. Follow Hungarian authorities and healthcare guidance for
> current protective action.

The page should link to official public-health guidance, including the World
Health Organization's hot-weather advice, without rewriting it into personalized
recommendations.

### Language rules

Use:

- "thermal stress category under the UTCI reference model";
- "the station measured";
- "the CAMS model estimated";
- "the European AQI category for this hourly concentration";
- "conditions coincided with" or "were consistent with poor ventilation";
- "data unavailable" and "coverage incomplete".

Avoid:

- "safe", "unsafe", "healthy", or "toxic" as Atlas's own judgement;
- "the air was clean" when a pollutant or station is missing;
- "you should" or advice based on age, disease, pregnancy, occupation, or
  activity level;
- causal claims from time-series correlation;
- a citywide number created by averaging a traffic station and a background
  station;
- regulatory exceedance/compliance claims based on the short-term AQI;
- treating modeled pollen or CAMS concentration as an observation.

### Explicit non-goals

Body & Breath is not an indoor-air model, wearable exposure tracker, diagnostic
tool, emissions inventory, legal-compliance dashboard, official alerting
service, or air-quality forecast product. It does not infer inhaled dose because
Atlas does not know a reader's location, time outdoors, ventilation rate,
building, route, or health status.

## 4. Evidence architecture

The feature should extend Atlas's existing evidence vocabulary rather than
invent a health-specific confidence score.

| Evidence label | Body & Breath use |
|---|---|
| Observed | Validated or up-to-date concentrations from named official monitoring stations; existing HungaroMet surface observations |
| Model-derived | ERA5-HEAT UTCI/MRT; CAMS concentration and pollen grids; model boundary-layer fields |
| Derived | UTCI/AQI categories, daily summaries, ventilation context, episode detection, correlations, and compound-hour counts |
| Remote-sensed | Optional aerosol/smoke or satellite context in a later release, never a station concentration substitute |

Every chart point needs a source tier, provider, location/grid-cell, timestamp,
unit, and quality/availability state. A modeled series should use a dashed line
and a `Model-derived` badge even when it agrees closely with a station.

## 5. Data required

### 5.1 Body: thermal environment

| Variable | Unit | Source priority | Role |
|---|---:|---|---|
| Universal Thermal Climate Index | deg C after conversion from K where necessary | ERA5-HEAT; validated local estimate as secondary product | Standardized outdoor thermal-stress measure |
| Mean radiant temperature | deg C | ERA5-HEAT | Radiative environment around the reference person |
| 2 m air temperature | deg C | HungaroMet observed; existing ERA5 continuous series as gap/context | Familiar reference and calculation input |
| Relative humidity or vapour pressure | %, hPa | HungaroMet/Open-Meteo | UTCI input and moisture context |
| 10 m wind speed | m/s | HungaroMet/Open-Meteo | UTCI input and ventilation context |
| Direct/diffuse/shortwave radiation | W/m2 or energy interval | existing Atlas fields | Explains radiant load; possible MRT method input |
| Cloud cover | % | existing Atlas fields | Radiative context |
| Sunrise/sunset and solar position | time/angle | existing pvlib path | Day/night segmentation |
| Event flags | boolean/time | existing Atlas phenomena | Heat, frost, inversion, fog, frontal change |

ERA5-HEAT defines the canonical historical UTCI product. It provides UTCI and
mean radiant temperature on a 0.25 degree hourly grid from 1940 to near real
time, plus longer-period statistics. It is a reanalysis-derived approximation
of a standard reference person and environment, not a sensor attached to a
human being.

### 5.2 Breath: station observations

Core pollutants:

| Pollutant | Canonical field | Unit | Why included |
|---|---|---:|---|
| Fine particulate matter | `pm2_5` | micrograms/m3 | Fine-particle burden; official background station reports it |
| Particulate matter | `pm10` | micrograms/m3 | Broad particulate burden and common station coverage |
| Nitrogen dioxide | `nitrogen_dioxide` | micrograms/m3 | Combustion/traffic-sensitive pollutant |
| Ozone | `ozone` | micrograms/m3 | Photochemical pollutant with different temporal behavior |
| Sulphur dioxide | `sulphur_dioxide` | micrograms/m3 | Secondary supporting pollutant |
| Carbon monoxide | `carbon_monoxide` | micrograms/m3 or provider unit retained | Secondary supporting pollutant; not part of European AQI maximum |

The official Hungarian monitoring inventory identifies at least two
complementary Debrecen sites:

- **Debrecen, Kalotaszeg ter** - urban-background classification; the inventory
  lists NO/NO2/NOx, SO2, CO, O3, PM10, PM2.5, and BTEX capabilities.
- **Debrecen, Hajnal utca** - urban-traffic classification; its pollutant set is
  narrower and traffic-sensitive.

Exact station codes, coordinates, operational dates, pollutant methods, and
current status must be resolved and pinned through the official/EEA station
metadata during implementation. Names are not stable primary keys. Critically,
the Hungarian authority's current list of stations reported internationally
includes **Debrecen Kalotaszeg**, but does not list Hajnal utca. The EEA adapter
may therefore provide only the background station. Atlas must not assume an EEA
series exists for Hajnal; the traffic comparison remains disabled until a
documented Hungarian machine endpoint or a confirmed EEA sampling point is
available.

Required station metadata:

```text
provider_station_id
national_station_code
eea_station_code
station_name
station_class (traffic/background/industrial/unknown)
area_class (urban/suburban/rural/unknown)
latitude, longitude, elevation
pollutant and sampling point identifiers
measurement method/equipment where supplied
valid_from, valid_to
metadata_retrieved_at_utc
```

### 5.3 Breath: model context

| Variable | Source | Intended use |
|---|---|---|
| PM2.5, PM10, NO2, O3, SO2, CO | CAMS Europe ensemble through Open-Meteo or ADS | Gridded context and comparison, not station replacement |
| European AQI and pollutant sub-indices | Recalculate from pinned EEA rules; provider value as check | Category display |
| Alder, birch, grass, mugwort, olive, ragweed pollen | CAMS Europe through Open-Meteo | Optional retrospective modeled context during supported seasons |
| Dust/aerosol optical depth | CAMS | Optional explanation for particulate episodes |
| Ensemble spread | Direct CAMS reanalysis/forecast products where available | Model uncertainty; later phase |

The model grid is roughly 0.1 degrees/11 km in Europe. It represents an area,
not the exact roadside or background station environment. Store both requested
and returned grid-cell coordinates.

### 5.4 Meteorological coupling fields

Body & Breath can reuse the existing 72-hour analysis rather than fetch a new
weather dataset:

- 10 m wind speed/direction and gust;
- boundary-layer height and ventilation diagnostic;
- low-level inversion evidence;
- precipitation timing and amount;
- pressure/frontal passages;
- temperature, dew point, solar radiation, and cloud;
- optional 850 hPa temperature/advection and 700 hPa vertical motion.

These fields explain dispersion and photochemistry qualitatively. They do not
identify emissions sources.

## 6. Source and API plan

### 6.1 ERA5-HEAT through the Copernicus Climate Data Store

The CDS dataset **Thermal comfort indices derived from ERA5 reanalysis** is the
canonical source for Body. Version 1.1 provides hourly UTCI and mean radiant
temperature from 1940 to near real time on a 0.25 degree grid, with daily,
monthly, seasonal, and annual statistics. The intermediate product is updated
daily; consolidated data follow with roughly two to three months of delay.

There is also a time-series delivery product intended for points and small
areas, with CSV and NetCDF output. It should be tested first because Atlas needs
one Debrecen grid point rather than global files.

Authentication and usage:

1. Create a CDS account and accept the dataset terms.
2. Configure the CDS personal API token outside the repository.
3. Open the dataset download form, select UTCI and MRT for the smallest spatial
   and temporal request, and use **Show API request**.
4. Execute the generated request through `cdsapi`.
5. Validate variable names, units, version, grid coordinates, time zone, missing
   values, and requested dates before writing an immutable shard.

```python
import cdsapi

client = cdsapi.Client()  # reads the user's external CDS credentials
request = {
    # Paste the selection generated by "Show API request" on the current
    # dataset form, then preserve a redacted copy in the shard manifest.
}
client.retrieve(
    "derived-utci-historical-timeseries",
    request,
    "era5-heat-debrecen.nc",
)
```

The request object is intentionally generated from the live form rather than
hard-coded here; CDS selection keys and delivery controls can change. Atlas
should save a redacted request manifest next to every shard.

Operational options:

| Option | Advantage | Cost/risk | Recommendation |
|---|---|---|---|
| Manual authenticated bootstrap, publish derived cache | Preserves no-secret CI; complete long history | Latest data require periodic manual refresh | v1 archive path |
| Protected `CDSAPI_KEY` workflow secret | Automated updates | Changes project's no-secret guarantee; CDS queue/lag can break runs | Optional later workflow only |
| Calculate reference-shade UTCI locally | Timely and no new API | Not ERA5-HEAT; radiation assumption; library validity bounds | Secondary product after validation |
| Use apparent temperature | Easy and already available | Not UTCI and cannot use UTCI categories | Never call it UTCI |

ERA5-HEAT must remain optional in the daily report integrity calculation. If it
lags yesterday's report, show its last available timestamp; do not hold back the
weather publication.

### 6.2 Hungarian official monitoring network

HungaroMet's air-quality portal is the authority for the national automatic
monitoring network, station inventory, and measurement pages. Its public web UI
is useful for human verification but no stable, documented machine API was
identified in the research for this specification. Atlas should not scrape
rendered HTML or reverse-engineer a private browser endpoint as a production
dependency.

Use the Hungarian pages to:

- verify station identity, classification, and measured pollutants;
- validate EEA metadata and sample values;
- link readers to the national authority;
- investigate station outages or national validation notes.

If HungaroMet later publishes a documented open endpoint and terms, it should
become the preferred observed source after an overlap comparison.

### 6.3 EEA station discovery

The European Environment Agency's ArcGIS station service is appropriate for
discovering and auditing internationally reported station metadata. Query
Hungary, then filter the returned geometry/names around Debrecen and pin the
resulting stable Kalotaszeg code in configuration. Absence of Hajnal from this
response is expected unless Hungary's international reporting changes; it is
not permission to invent an identifier.

Illustrative request:

```text
GET https://air.discomap.eea.europa.eu/arcgis/rest/services/
    AirQuality/AirQualityDownloadServiceEUMonitoringStations/MapServer/0/query
    ?where=CountryCode%3D%27HU%27
    &outFields=AirQualityStation,Country,CountryCode,EoICode,
               AQStationName,stationClass,PopupInfo
    &returnGeometry=true
    &f=geojson
```

Before relying on it, run a contract check that confirms the layer ID and field
names advertised by the service metadata. Cache the complete metadata response
and record retrieval time. Station discovery should run manually or weekly,
not on every report.

### 6.4 EEA concentration downloads

The EEA data hub provides both up-to-date (UTD) and verified air-quality data
from 2013 onward as downloadable Parquet and through a new API/download service.
For Debrecen, this path should initially be scoped to internationally reported
Kalotaszeg sampling points returned by discovery. The former legacy export
service was discontinued on 31 December 2024 and must not be implemented.

Implementation sequence:

1. Use the current EEA data-download application to discover the supported
   request schema for Hungary, pinned stations, pollutants, and dates.
2. Prefer Parquet for complete/verified historical ingestion and a narrowly
   filtered UTD request for the latest 72 hours.
3. Save the exact request parameters, response headers, URL, file digest, and
   retrieval timestamp in a sidecar manifest.
4. Normalize the provider's sampling-point/station identifiers without
   discarding them.
5. Preserve verification, validity, aggregation, and unit fields.
6. Reject unknown units or pollutant codes instead of guessing.
7. Compare a small sample to the Hungarian official portal before launch.

UTD measurements can arrive within hours but are not yet fully validated. The
EEA viewer describes a short reporting delay and uses a daily completeness rule
of at least 75% valid hourly values. Atlas should adopt the 18-of-24-hour rule
for daily descriptive summaries, while retaining every valid hour in the
timeline.

The EEA viewer's displayed time convention is not a safe parsing rule for
Budapest daylight-saving time. Parse the timestamp and explicit offset from raw
data, normalize to UTC, then derive local time with `Europe/Budapest`.

### 6.5 CAMS Europe through Open-Meteo

Open-Meteo exposes the CAMS European air-quality forecast and reanalysis through
a stable JSON API without a key for the current non-commercial use pattern. It
is the simplest no-secret model-context integration.

Historical/model-context example:

```text
GET https://air-quality-api.open-meteo.com/v1/air-quality
    ?latitude=47.5316
    &longitude=21.6273
    &hourly=pm10,pm2_5,nitrogen_dioxide,ozone,
            sulphur_dioxide,carbon_monoxide,european_aqi
    &domains=cams_europe
    &timezone=UTC
    &start_date=2026-08-19
    &end_date=2026-08-21
```

Optional pollen adds:

```text
alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,olive_pollen,ragweed_pollen
```

Response validation must check:

- HTTP status and the API's structured error response;
- returned latitude, longitude, elevation, timezone, and UTC offset;
- exact hourly array lengths and monotonic timestamps;
- `hourly_units` for every requested variable;
- null values, especially pollen outside the supported season;
- source domain is `cams_europe`, never an automatic global fallback;
- retrieval and provider model/update metadata.

Open-Meteo documents 0.1 degree hourly CAMS Europe data, reanalysis from 2013
onward, and the 2024 European AQI bands. Pages using these data must credit both
Open-Meteo and the CAMS ensemble provider as required by the provider docs.

### 6.6 Direct CAMS Atmosphere Data Store

CAMS European air-quality reanalysis provides a validated ensemble on a 0.1
degree hourly grid from 2013, including ensemble spread. Direct ADS ingestion is
scientifically richer than the proxy because Atlas can retain model uncertainty
and precise dataset version. It also requires an account, terms acceptance, API
credentials, more complex requests, and additional storage.

Support it as a later research/bootstrap provider, not the first operational
adapter. A source switch from Open-Meteo/CAMS to direct ADS is a new series
version and requires an overlap audit.

### 6.7 Source matrix

| Product | Source | Auth | Evidence | Latency/coverage | Operational role |
|---|---|---|---|---|---|
| UTCI + MRT | ERA5-HEAT CDS | Account/token | Model-derived | 1940-near real time; intermediate/consolidated lag | Canonical thermal archive |
| Local shade-reference UTCI | Existing weather + reviewed UTCI implementation | None beyond current sources | Derived from observed/model inputs | Timely | Optional secondary current estimate |
| Station pollutants | EEA UTD/verified downloads | Public service; verify current terms | Observed | 2013 onward in EEA data hub; UTD provisional; internationally reported sites only | Canonical Kalotaszeg evidence |
| Station metadata | EEA ArcGIS + Hungarian portal | None | Metadata | EEA and national network scopes differ | Discovery/audit |
| Gridded pollutants | CAMS via Open-Meteo | No key for current use | Model-derived | CAMS Europe 2013 onward; forecast/reanalysis differ | Context and gap visibility |
| Model pollen | CAMS via Open-Meteo | No key for current use | Model-derived | Europe, supported pollen season | Optional context |
| Direct ensemble/spread | CAMS ADS | Account/token | Model-derived | Product-specific | Later uncertainty research |

## 7. Thermal method

### 7.1 What UTCI represents

UTCI combines air temperature, humidity/water vapour, wind at 10 m, and mean
radiant temperature into an equivalent temperature for a standardized reference
person and activity. It is intentionally comparable across environments, but it
is not personalized. Clothing and physiology in the model adapt according to
the standard; Atlas must not imply that the result represents every person.

Use degrees Celsius in the UI. If ERA5-HEAT is delivered in kelvin, convert with
`degC = K - 273.15` after checking metadata; never infer units from magnitude.

### 7.2 UTCI categories

Use the official ten-category scale and persist the threshold version:

| UTCI equivalent temperature | Category |
|---:|---|
| above +46 deg C | Extreme heat stress |
| +38 to +46 deg C | Very strong heat stress |
| +32 to +38 deg C | Strong heat stress |
| +26 to +32 deg C | Moderate heat stress |
| +9 to +26 deg C | No thermal stress |
| 0 to +9 deg C | Slight cold stress |
| -13 to 0 deg C | Moderate cold stress |
| -27 to -13 deg C | Strong cold stress |
| -40 to -27 deg C | Very strong cold stress |
| below -40 deg C | Extreme cold stress |

Boundary ownership must be encoded once and unit-tested so a value exactly at a
threshold cannot enter two categories. The source standard's inclusivity should
be copied into the model card.

### 7.3 Hourly and daily Body metrics

For each complete local day calculate:

- minimum, mean, maximum UTCI and their local times;
- hours in every UTCI stress category;
- longest continuous run at or above moderate heat stress;
- longest continuous run at or below moderate cold stress;
- maximum `MRT - air_temperature` and time;
- daylit median/max UTCI and nighttime median/min UTCI;
- overnight recovery: minimum UTCI from 22:00 through 06:00 local, with the
  window assigned to the evening date;
- thermal range and change over the 72-hour period;
- tropical-night flag from air temperature using Atlas's existing phenomenon
  definition, kept separate from UTCI;
- completeness, source version, and whether any input was estimated.

No daily metric is valid unless its required hourly coverage passes a declared
threshold. Suggested defaults are at least 18 valid hours for an all-day
summary, at least 75% of the daylight window for radiant summaries, and at
least 6 of 8 hours for overnight recovery. Publish the numerator and denominator.

### 7.4 Optional local reference-shade UTCI

A timely secondary series can be calculated with a reviewed implementation such
as `pythermalcomfort.models.utci` using air temperature, relative humidity, 10 m
wind, and `mean_radiant_temperature = air_temperature`. This represents a
radiation-neutral/reference-shade assumption; it is not a sun-exposed human and
not ERA5-HEAT.

```python
from pythermalcomfort.models import utci

result = utci(
    tdb=air_temperature_c,
    tr=air_temperature_c,
    v=wind_speed_10m_ms,
    rh=relative_humidity_percent,
    limit_inputs=True,
)
```

Implementation rules:

- preserve whether each input is observed or model-derived;
- do not extrapolate beyond the implementation's validity limits;
- retain `NaN` with an explicit reason when inputs are outside range;
- compare at least a full warm and cold season against ERA5-HEAT UTCI;
- show bias, mean absolute error, category confusion, and solar-time dependence;
- label it `Reference-shade UTCI estimate` everywhere;
- never splice it into the ERA5-HEAT series as though one homogeneous record.

A later all-sky MRT calculation may use Atlas radiation and solar geometry, but
only after peer-reviewed equations, surface assumptions, longwave radiation,
human geometry, and validation are fully specified. A simplistic solar offset
is not acceptable.

## 8. Air-quality method

### 8.1 Canonical normalized observation

Store one row per station, sampling point, pollutant, and provider interval:

| Field | Type | Requirement |
|---|---|---|
| `station_id` | string | Atlas stable ID mapped to provider IDs |
| `sampling_point_id` | string | Preserve source identifier |
| `station_name` / `station_class` | string/enumeration | Human context |
| `latitude`, `longitude` | float | Source coordinates |
| `pollutant` | enumeration | Canonical name plus original notation |
| `concentration` | float/null | Never coerce missing to zero |
| `unit` | string | Validated and normalized where supported |
| `start_utc`, `end_utc` | timestamp | Explicit averaging interval |
| `averaging_period` | duration | Do not assume one hour |
| `validity` | source enumeration | Preserve raw code and normalized state |
| `verification` | source enumeration | UTD/provisional or verified |
| `source_dataset_version` | string | Provenance |
| `retrieved_at_utc` | timestamp | Freshness |
| `raw_digest` | string | Audit path |

Retain original concentration/unit fields alongside normalized values when unit
conversion occurs. Gas conversion between mass and volume concentration depends
on assumptions; Atlas should prefer provider-supplied micrograms/m3 and must not
perform an undocumented conversion.

### 8.2 Quality and completeness

Normalize provider flags into:

```text
valid
provisional_valid
questionable
invalid
missing
unknown
```

- `valid` and `provisional_valid` may enter the hourly timeline, with different
  badges.
- `questionable` may be shown for transparency but is excluded from categories
  and summaries by default.
- `invalid`, `missing`, and `unknown` never become a number.
- A daily station/pollutant summary needs at least 18 valid hourly values when
  the expected cadence is hourly.
- Do not interpolate station concentrations for category or peak metrics.
- Never infer good conditions from missing data.

Publish a coverage ledger for every station/pollutant/day. Station outages are
part of the evidence story, not a UI inconvenience to conceal.

### 8.3 European Air Quality Index

Use the European Environment Agency's revised 2024 hourly bands. The provider
documentation applies hourly concentrations to all five index pollutants and
defines the overall index as the highest pollutant-specific index.

| Hourly concentration (micrograms/m3) | Good | Fair | Moderate | Poor | Very poor | Extremely poor |
|---|---:|---:|---:|---:|---:|---:|
| PM2.5 | 0-5 | 5-15 | 15-50 | 50-90 | 90-140 | >140 |
| PM10 | 0-15 | 15-45 | 45-120 | 120-195 | 195-270 | >270 |
| NO2 | 0-10 | 10-25 | 25-60 | 60-100 | 100-150 | >150 |
| O3 | 0-60 | 60-100 | 100-120 | 120-160 | 160-180 | >180 |
| SO2 | 0-20 | 20-40 | 40-125 | 125-190 | 190-275 | >275 |

Associated numeric index bands are 0-20, 20-40, 40-60, 60-80, 80-100,
and above 100. If Atlas publishes a continuous numeric value, interpolate using
the official method and test every boundary. The category, concentration, unit,
dominant pollutant, station, rules version, and provisional/verified status must
remain visible; a naked number is insufficient.

Important constraints:

- calculate an index per station and hour;
- never take the maximum pollutant from different stations to fabricate one
  physical station index;
- the page may summarize the worst available station category, but must name
  the station and pollutant and let the reader see both stations;
- if a required pollutant is missing, calculate from the available five but
  show exactly which were unavailable;
- CO is displayed but does not determine the European AQI maximum;
- the short-term index is communication context, not an assessment of EU
  annual/daily legal compliance.

Pin the rules as data, for example `eea_eaqi_2024.json`, with source URL,
retrieval date, units, bands, boundary semantics, and checksum. A future EEA
revision creates a new rules version and a documented historical-recalculation
decision.

### 8.4 Episodes

Atlas may identify an objective **elevated-concentration period**, not an
official pollution episode or warning:

- starts when a valid station/pollutant reaches at least the configured AQI
  category for two consecutive hours;
- ends after two consecutive valid hours below it;
- breaks on a missing gap longer than the allowed single-hour bridge;
- stores station, pollutant, category threshold, peak, duration, completeness,
  rules version, and source validation state.

The default threshold should remain a product choice in configuration and be
described literally. Do not choose it to maximize event count. Official
Hungarian alerts should be a separate data type if a documented source is later
added.

### 8.5 Station comparison

Kalotaszeg ter and Hajnal utca should appear side by side **when both have a
documented machine-readable series** because their site classes answer different
questions. A traffic monitor may legitimately record a short NO2/PM peak absent
at an urban-background site. V1 must be fully useful with Kalotaszeg alone; a
grey metadata card may explain that the desirable traffic comparison is not
available through the selected EEA feed.

- never arithmetic-average stations;
- show distance, station class, and available pollutants;
- preserve each sampling point's method and interval;
- state when only one site is operating;
- provide paired difference plots only for simultaneous valid hours and with
  sample size;
- do not call either station representative of every Debrecen neighbourhood.

### 8.6 Weather coupling

Derived exploratory diagnostics may include:

- concentration versus wind speed, coloured by direction sector;
- PM/NO2 during inversion versus non-inversion hours;
- pollutant change before/after an Atlas frontal passage;
- ozone versus radiation and temperature during daylight;
- wet removal context around precipitation;
- concentration versus ventilation metric or boundary-layer height;
- lagged correlations from -12 to +12 hours.

Each view must show number of paired valid hours and use language such as
"coincided with". These diagnostics cannot identify a source, establish
causation, or account for traffic/emissions schedules and long-range transport.
Do not fit a complicated predictive model for v1.

## 9. Compound Body + Breath view

### 9.1 No combined score

Display a matrix of co-occurring categories instead of a weighted sum:

```text
                         Breath / EEA category
Body / UTCI group     Good-Fair   Moderate   Poor+
No thermal stress         18 h       3 h       0 h
Moderate heat              7 h       4 h       1 h
Strong+ heat               0 h       2 h       0 h
```

Every cell is an hour count with a paired-data denominator. Let users choose a
station; do not merge stations. Cold categories use the same matrix in cold
seasons. A missing row/column is shown as unavailable, never zero exposure.

### 9.2 Compound intervals

Atlas may state, for example:

> Strong UTCI heat stress and a Moderate station AQI overlapped for two valid
> hours at Kalotaszeg ter. The AQI category was determined by ozone. This is an
> environmental co-occurrence, not a personal exposure or health-risk score.

Store start/end, thermal source, station, dominant pollutant, categories,
coverage, and source status. If Body is model-derived and Breath observed, both
badges remain visible in the sentence and download.

## 10. Data products and contracts

### 10.1 Processed files

```text
data/raw/era5_heat/<version>/<year>/...
data/raw/air_quality/eea/<retrieval>/<files-and-manifest>
data/raw/air_quality/open_meteo_cams/<date-range>.json

data/processed/thermal_comfort_hourly.parquet
data/processed/thermal_comfort_daily.parquet
data/processed/air_quality_stations.parquet
data/processed/air_quality_observations.parquet
data/processed/air_quality_model.parquet
data/processed/air_quality_hourly_index.parquet
data/processed/body_breath_compound_intervals.parquet
data/processed/body_breath_current.json

site/analysis/data/body-breath/
  current.json
  stations.json
  hourly.json
  methods.json
```

Publish CSV/JSON projections for browser use and downloads. Parquet remains the
canonical analytical store. Raw provider material remains cached/ignored unless
its licence and size make versioned storage appropriate.

### 10.2 Thermal hourly schema

| Column | Type | Meaning |
|---|---|---|
| `time_utc`, `time_local` | timestamp | Explicit timezone keys |
| `local_date` | date | Atlas reporting join |
| `utci_c` | float/null | UTCI equivalent temperature |
| `utci_category` | enum/null | Versioned standard category |
| `mrt_c` | float/null | Mean radiant temperature |
| `air_temperature_c` | float/null | Context/input |
| `relative_humidity_percent` | float/null | Context/input |
| `wind_speed_10m_ms` | float/null | Context/input |
| `thermal_product` | enum | `era5_heat` or `reference_shade_estimate` |
| `evidence_tier` | enum | Model-derived or Derived |
| `source_version` | string | Dataset/calculation identity |
| `validity_reason` | string/null | Missing/out-of-range explanation |

### 10.3 Current summary JSON

```json
{
  "schema_version": "1.0.0",
  "period": {"start_utc": "...", "end_utc": "..."},
  "thermal": {
    "product": "era5_heat",
    "latest_available_utc": "...",
    "peak_utci_c": 31.4,
    "peak_category": "moderate_heat_stress",
    "valid_hours": 68,
    "expected_hours": 72
  },
  "air_quality": {
    "stations": [
      {
        "station_id": "pinned-provider-id",
        "station_class": "urban_background",
        "verification": "up_to_date_provisional",
        "worst_category": "moderate",
        "dominant_pollutant": "ozone",
        "valid_hours": 70,
        "expected_hours": 72
      }
    ]
  },
  "compound": {"paired_valid_hours": 66, "interval_count": 1},
  "generated_at_utc": "..."
}
```

Example numbers are illustrative only and must not become fixtures presented as
real Debrecen observations.

### 10.4 Configuration

```yaml
body_breath:
  enabled: true
  required: false
  timezone: Europe/Budapest
  thermal:
    era5_heat_enabled: true
    era5_heat_version: "1.1"
    reference_shade_enabled: false
    minimum_daily_coverage: 0.75
  air_quality:
    observed_provider: eea
    stations:
      - id: to-be-pinned-kalotaszeg-code
        provider: eea
        expected_class: urban_background
    optional_comparison_stations:
      - id: null
        provider: hungarian_official
        name: Debrecen Hajnal utca
        expected_class: urban_traffic
        enabled: false
        requires_documented_machine_source: true
    pollutants: [pm2_5, pm10, nitrogen_dioxide, ozone, sulphur_dioxide, carbon_monoxide]
    minimum_daily_coverage: 0.75
    eaqi_rules: eea_eaqi_2024
    model_context_provider: open_meteo_cams_europe
    never_fill_observation_gaps: true
  pollen:
    enabled: false
    retrospective_only: true
```

Unknown station codes must prevent the relevant observed adapter from starting.
The Kalotaszeg placeholder is deliberately not inferred from its name. The
Hajnal entry is metadata-only and disabled until its source requirement is met.

## 11. Software architecture

### 11.1 Modules

| Module | Responsibility |
|---|---|
| `atlas/thermal_comfort.py` | ERA5-HEAT normalization, UTCI categories, optional local calculation, daily summaries |
| `atlas/air_quality_ingest.py` | EEA metadata/download adapters and Open-Meteo CAMS requests |
| `atlas/air_quality.py` | Station data model, quality normalization, EEA index, episodes, comparisons |
| `atlas/body_breath.py` | Join thermal, air, and meteorological context; compound intervals and narrative facts |
| `atlas/body_breath_plots.py` | Synchronized lanes, pollutant small multiples, matrix, station comparison |

Add typed configuration dataclasses under the existing root configuration.
Network clients should use existing retry, cache, timeout, user-agent, and
provenance conventions.

### 11.2 Pipeline position

```text
HungaroMet/Open-Meteo weather -------------------------+
ERA5-HEAT -> thermal normalization -> Body metrics     |
                                                        +-> Body & Breath synthesis
EEA stations -> quality normalization -> hourly AQI    |
CAMS model context -> separate normalized series ------+
                                                               |
                                                               v
                                               analysis page + daily card
```

Observed and modeled concentration paths may meet in a comparison object, but
must remain separate tables/series. The synthesis layer receives evidence tags
and is not allowed to replace missing observations.

### 11.3 Commands

```powershell
atlas-body-breath discover-stations --country HU --near 47.5316,21.6273
atlas-body-breath audit-stations --config configs/atlas.yml
atlas-body-breath bootstrap-era5-heat --start 1991-01-01 --end 2020-12-31
atlas-body-breath fetch-air --start 2026-08-19 --end 2026-08-21
atlas-body-breath validate-overlap --start 2025-01-01 --end 2025-12-31
atlas-body-breath export-site
```

Discovery and bootstrap are manual/release operations. Recent observed/model
fetch and export may run daily. Commands must support offline fixture mode.

## 12. UI and interaction specification

### 12.1 Information architecture

- Add `site/analysis/body-breath.html` to the 72-Hour Analysis family.
- Add a **Body & Breath** overview card containing peak UTCI/category, overnight
  recovery, worst available observed station AQI/category, dominant pollutant,
  and paired completeness.
- The Daily Report receives one compact section with yesterday's valid summary
  and a link to the 72-hour page.
- The Archive may later expose annual thermal/AQ calendars, but v1 should not
  crowd the existing archive navigation.

### 12.2 Page opening

The top of the page contains:

1. publication-state strip with period, latest observation, ERA5-HEAT latency,
   and overall component integrity;
2. safety/scope statement;
3. four fact cards:
   - peak UTCI, time, category, and product;
   - overnight recovery minimum and valid hours;
   - worst observed AQI category, time, pollutant, and station;
   - paired Body/Breath coverage and overlap duration;
4. compact evidence legend.

If no observed air data exists, the third fact card says "Official station data
unavailable". A CAMS value may appear in a separate card but cannot occupy that
slot under an Observed heading.

### 12.3 Synchronized 72-hour lanes

The primary chart has one common time cursor and aligned local-time axis:

```text
BODY    UTCI ribbon by stress category
        air temperature, MRT, UTCI lines; daylight shading

BREATH  selected station's overall AQI ribbon
        pollutant concentrations as selectable small multiples

EVENTS  rain, frontal passage, inversion, low ventilation markers
```

Hover/focus at an hour opens one accessible detail block with:

- local and UTC time;
- UTCI value, category, source product, air temperature, and MRT;
- station, pollutant concentrations/categories, dominant pollutant, and quality;
- model-context values in a visually separate row;
- relevant weather evidence;
- which inputs are missing.

Do not put pollutants with different scales on one axis. Use aligned small
multiples, a pollutant selector, or indexed category ribbons.

### 12.4 Body section

Required views:

- air temperature, MRT, and UTCI lines with stress-band background;
- `MRT - air temperature` radiant-load strip;
- day/night and overnight-recovery summary;
- hours by UTCI category;
- comparison with the same calendar window in 1991-2020 after a complete
  ERA5-HEAT reference is available;
- clear product toggle if both ERA5-HEAT and reference-shade estimate exist,
  never a merged line.

The chart copy should explain why UTCI may differ from air temperature without
using the vague phrase "feels like" as the only definition.

### 12.5 Breath section

Required controls:

| Control | Default | Behavior |
|---|---|---|
| Station | urban background | Switching retains time and pollutant state |
| Pollutant | dominant/worst for period | Shows concentration and own EEA category |
| Evidence | observed | Optional model context overlays as dashed series |
| Validation | valid + provisional | Toggle may hide provisional, never invalid |
| Time | 72 hours | Optional daily aggregation only when coverage passes |

Required views:

- small station map with exact site class and no citywide interpolation;
- station/pollutant availability matrix;
- pollutant timeline with category bands and unit;
- observed versus CAMS comparison with matched times and separate evidence
  badges;
- traffic/background paired difference where coverage overlaps;
- coverage and validation ledger;
- source download links.

The overall colour ribbon always identifies the pollutant that determined it.
When two pollutants tie, show both.

### 12.6 Compound section

- category co-occurrence matrix with raw hour counts and denominator;
- list of overlap intervals, sorted by time rather than severity theatre;
- station selector;
- concise weather context for each interval;
- no gauge, score, ranking, skull icon, or alarm animation.

### 12.7 Weather coupling section

Offer a small number of precomputed, legible diagnostics rather than an
open-ended dashboard:

- wind/concentration polar or binned plot;
- ventilation versus PM/NO2 scatter;
- solar radiation/temperature versus ozone daylight scatter;
- annotated timeline around the most relevant front/rain/inversion.

Each includes paired sample size, missingness, method text, and a warning that
association is not source attribution.

### 12.8 URL state

```text
?station=<pinned-id>
&pollutant=pm2_5
&evidence=observed
&thermal=era5_heat
&section=compound
```

All parameters use an allow-list. A shared URL restores selected station,
pollutant, evidence tier, thermal product, and focused interval.

### 12.9 Accessibility and visual rules

- Never rely on the conventional green-to-purple/red AQI palette alone. Add
  category names, hatch/pattern or boundary lines, and pollutant icons/text.
- Use distinct line styles and direct labels for observed/model-derived series.
- Give every chart a synchronized table and concise text summary.
- Keyboard focus follows time points; station/pollutant controls are native form
  controls with persistent labels.
- Respect reduced motion and never autoplay.
- Preserve category contrast in Windows High Contrast and monochrome print.
- On mobile, replace dense hover interactions with expandable hourly/daily rows.
- Do not hide critical source/quality text in a tooltip.
- Use proper chemical notation in visible text while keeping plain ASCII field
  names in downloads.

## 13. Existing examples and what to borrow

| Example | Useful idea | Atlas adaptation |
|---|---|---|
| Copernicus Thermal Trace | Long historical UTCI/heat-cold stress exploration and clear category geography | Add hour-level Debrecen narrative, MRT explanation, and source latency |
| ERA5-HEAT dataset/application | Standardized UTCI plus MRT and daily statistics | Keep reanalysis evidence explicit; do not personalize |
| EEA European Air Quality Index | Station/model separation, dominant-pollutant concept, category communication | Preserve station class, quality state, and downloadable raw values |
| EEA UTD viewer | Recent station measurements and completeness concepts | Parse raw timestamps correctly and avoid relying on the viewer as an API |
| CAMS European forecast plots | Species selectors and spatial model context, including pollen | Retrospective dates only in Atlas and model badges everywhere |
| Atlas Storms & Satellite | Synchronized time cursor and multiple evidence lanes | Reuse the interaction grammar for Body/Breath/weather alignment |
| Atlas Methods & Evidence | Provenance badges and downloads | Extend with station validation and rules-version ledgers |

Thermal Trace is the closest product precedent for making UTCI history
accessible. The EEA index is the correct communication precedent for short-term
European station air quality. Atlas's distinctive contribution is the careful
time-aligned explanation of thermal load, measured pollutants, and meteorology
for one place, without pretending that a compound environmental story is a
personal health verdict.

## 14. Provenance, licences, privacy, and security

### Provenance

Every generated page and download must include:

- provider and dataset/product name;
- station or returned grid cell;
- source version and retrieval timestamp;
- observed/model-derived/derived label;
- units and aggregation interval;
- validity/verification and completeness;
- category/rules version;
- changes Atlas made, including aggregation and index calculation.

### Attribution and licences

- ERA5-HEAT output requires the applicable Copernicus/ECMWF attribution,
  licence notice, and disclaimer.
- Open-Meteo CAMS pages must credit Open-Meteo and the CAMS ensemble providers
  in the form required by the current API documentation.
- EEA data reuse must follow the current EEA data policy and retain provider
  attribution/metadata.
- Hungarian station metadata and links must credit the national authority and
  be checked against the portal's terms before republishing substantial data.
- Record the exact licence URL and access date in source manifests; do not rely
  on this design document as the licence record.

### Privacy

The proposed feature processes public environmental data and asks for no user
location, profile, health information, or wearable data. Do not add personal
profiles, activity recommendations, symptom logs, or precise user geolocation
without a separate privacy and safety design.

### Credentials

CDS/ADS tokens live only in the user's credential store or protected CI secret.
Never place them in YAML, request manifests, logs, generated pages, test
fixtures, or error messages. The default report remains functional without
them.

## 15. Performance and operations

### Fetch and cache policy

- EEA station metadata: cache for 7-30 days; force refresh manually after a
  network change.
- EEA UTD data: fetch only the necessary rolling window plus a correction
  overlap; raw response immutable by retrieval ID.
- EEA verified history: append immutable Parquet partitions by year/pollutant;
  reconcile revisions through a manifest, never silent overwrite.
- CAMS/Open-Meteo: one batched coordinate/request for the period and variables;
  cache raw JSON using the normalized request hash.
- ERA5-HEAT: resumable annual/monthly or time-series shards; bootstrap outside
  the routine Pages build.
- Browser: publish compact JSON for 72 hours; lazy-load history/diagnostics.

### Freshness policy

Freshness is per component:

```text
weather observation latest timestamp
air station latest timestamp per station/pollutant
air verification state and retrieval time
CAMS model valid time and retrieval time
ERA5-HEAT latest available time/version
page generation time
```

Do not display a single "updated" time that conceals a stale thermal or station
series.

### Optionality

`body_breath.required` should remain false. Provider outage, token absence, or
station maintenance must not block the core meteorological report. The page and
overview card should degrade section by section and state why.

## 16. Failure states

| Failure | Required behavior |
|---|---|
| Station returns no row | Show unavailable with requested station/pollutant/time; never zero |
| Only traffic or background site works | Publish that site and state the missing comparison |
| EEA UTD is provisional | Show provisional badge on chart, fact card, and download |
| Verified archive revises a value | Version the raw retrieval and rebuild derived metrics with an audit note |
| Unknown pollutant/unit/interval | Quarantine the rows and fail that series validation |
| CAMS exists but station is absent | Keep CAMS in model context; observed card remains unavailable |
| ERA5-HEAT lags the period | Show latest thermal date or validated separate estimate; never forward-fill |
| Local UTCI input outside validity bounds | Return missing with reason; do not clamp invisibly |
| UTCI/AQI rules file missing or corrupt | Publish raw valid values without category, and raise component integrity issue |
| Local clock has 23/25 hours | Calculate expected hours from timezone-aware day boundaries |
| JavaScript fails | Render facts, hourly/daily table, coverage, and source links server-side |

## 17. Tests and validation

### 17.1 Unit tests

- kelvin/Celsius validation and conversion;
- every UTCI category boundary, including exact threshold values;
- EEA AQI category and interpolation boundaries for all five pollutants;
- overall station AQI selects the maximum available pollutant and preserves
  ties;
- CO cannot determine the European AQI;
- null concentration never becomes zero or Good;
- validity and verification flag normalization;
- unit rejection/conversion rules;
- hourly coverage on 23-, 24-, and 25-hour Budapest days;
- episode start/end, single missing-hour bridge, and longer-gap break;
- overnight window across midnight and DST;
- compound matrix uses only paired valid hours;
- station comparison cannot average different sites;
- returned CAMS grid coordinates and units are retained;
- serialized schema and rules-version compatibility.

### 17.2 Adapter contract tests

- EEA station service layer/fields still exist;
- configured station IDs resolve to expected name, location, and class;
- current EEA download returns expected columns and provider metadata;
- one small downloaded sample matches an official portal view within display
  rounding;
- Open-Meteo request uses `cams_europe`, UTC, exact date range, and expected
  variables;
- CDS fixture includes expected UTCI/MRT metadata and version;
- HTTP retry does not duplicate rows or accept a partial file.

Live contract checks should be separate from deterministic offline tests and
should not expose credentials.

### 17.3 Scientific validation

For reference-shade UTCI, compare against ERA5-HEAT by hour, month, UTCI
category, solar elevation, wind regime, and air-temperature range. Publish:

- bias, mean absolute error, and robust percentile error;
- category confusion matrix;
- missing/out-of-validity share;
- worst disagreement examples;
- clear conclusion on whether it is fit for the intended label.

For CAMS versus stations, compare only matched valid times and report by
station/pollutant/season:

- bias, mean absolute error, correlation with uncertainty;
- category agreement and false-category rates;
- coverage and grid/station mismatch;
- effect of provisional versus verified station values.

These comparisons evaluate context fitness; they must not be used to bias-correct
or fill station observations in v1.

### 17.4 UI and accessibility tests

- keyboard traversal of time, station, pollutant, and evidence controls;
- screen-reader names include value, unit, category, source, and validity;
- category comprehension without colour;
- observed/model distinction in monochrome and high contrast;
- narrow mobile layout and table fallback;
- exact empty/stale/provisional/missing-pollutant states;
- common cursor updates the accessible detail block;
- deep links restore state;
- no medical recommendation appears in generated narratives.

### 17.5 Narrative tests

Use deterministic phrase templates with prohibited-language tests. Assertions
should reject claims such as `safe`, `clean air` from partial data, `caused by`
from correlations, or `observed` on CAMS/ERA5-HEAT values. Every peak statement
must carry time, location/product, source tier, and completeness.

## 18. Rollout plan and acceptance gates

### Phase 0 - provider audit

Resolve/pin the EEA-reported Kalotaszeg station/sampling-point codes, confirm
whether any valid machine series exists for Hajnal, download a small EEA UTD and
verified sample, inspect licence/metadata, fetch a CAMS overlap, and retrieve a
small ERA5-HEAT time series.

**Gate:** stable documented paths, units/intervals understood, station values
cross-checked, credentials isolated.

### Phase 1 - Breath Observed

Implement station metadata, EEA observation normalization, quality flags,
coverage ledger, pollutant timelines, and 2024 European AQI categories.

**Gate:** no station averaging, missing-is-not-good tests pass, UTD status is
visible, 72-hour page works offline from fixtures.

### Phase 2 - Breath Model Context

Add CAMS/Open-Meteo pollutant series and direct observed-versus-model comparison.

**Gate:** model cannot populate observed fields; returned grid cell and CAMS
attribution shown; overlap validation published.

### Phase 3 - Body Reanalysis

Bootstrap ERA5-HEAT UTCI/MRT, add thermal categories, radiant-load explanation,
overnight recovery, and seasonal reference context.

**Gate:** complete source/version/units audit, timezone coverage tests, and
latency-specific empty state.

### Phase 4 - Synchronized Body & Breath

Publish common time cursor, evidence detail, compound matrix, overlap intervals,
and overview/daily cards.

**Gate:** paired-hour denominator visible, no combined score, accessibility and
mobile reviews pass.

### Phase 5 - Current thermal estimate

Evaluate and, only if fit, publish the separate reference-shade UTCI estimate.

**Gate:** warm/cold seasonal validation, category confusion reviewed, bounds and
product label visible, no splicing into ERA5-HEAT.

### Phase 6 - Deeper context

Optionally add pollen, aerosol/dust, direct CAMS ensemble spread, archive
calendars, and weather-coupling diagnostics.

**Gate:** retrospective scope preserved, new licences documented, performance
budget maintained, claims remain descriptive.

## 19. Definition of done for v1

Body & Breath v1 is complete only when:

- every enabled official Debrecen station ID, class, coordinate, and pollutant
  coverage is pinned and audited, with EEA and national-network scope kept
  distinct;
- observed concentrations preserve provider quality and verification state;
- missing and invalid data cannot generate a Good category;
- European AQI calculations use a versioned, tested official rules file;
- traffic and background stations remain separate;
- UTCI product/source/version and MRT are explicit;
- the 72-hour page exposes per-component freshness and completeness;
- thermal and AQ categories can be understood without colour;
- observed and model-derived series remain visually and structurally distinct;
- compound results report paired valid hours and never become a health score;
- every chart has a table/text alternative and source download;
- optional source failure cannot block the core Atlas report;
- safety copy and generated-language tests prevent personalized medical advice;
- README, methods, and data-source documentation include the feature and its
  licences/limitations.

## 20. Source register

Primary and scientific sources consulted for this specification, accessed
2026-08-22:

- [ERA5-HEAT thermal comfort dataset](https://cds.climate.copernicus.eu/datasets/derived-utci-historical?tab=overview)
- [ERA5-HEAT point/time-series dataset](https://cds.climate.copernicus.eu/datasets/derived-utci-historical-timeseries?tab=download)
- [ERA5-HEAT documentation and time-series delivery](https://confluence.ecmwf.int/plugins/viewsource/viewpagesrc.action?pageId=650383669)
- [ERA5-HEAT dataset paper](https://centaur.reading.ac.uk/91423/9/gdj3.102.pdf)
- [Universal Thermal Climate Index reference material](https://utci.org/resources/utci_poster.pdf)
- [ECMWF thermal stress and heat-index documentation](https://confluence.ecmwf.int/pages/viewpage.action?pageId=473828332)
- [pythermalcomfort UTCI implementation documentation](https://pythermalcomfort.readthedocs.io/en/stable/_modules/pythermalcomfort/models/utci.html)
- [Copernicus Thermal Trace application description](https://climate.copernicus.eu/thermal-trace-decades-heat-and-cold-stress-data-your-fingertips)
- [Hungarian automatic air-quality monitoring stations](https://legszennyezettseg.met.hu/levegominoseg/automata-meroallomasok)
- [Hungarian automatic-network measurement data](https://legszennyezettseg.met.hu/levegominoseg/meresi-adatok/automata-merohalozat)
- [Hungarian stations in international reporting](https://legszennyezettseg.met.hu/levegominoseg/nemzetkozi-adatszolgaltatasba)
- [EEA air-quality data service metadata](https://www.eea.europa.eu/en/datahub/datahubitem-view/778ef9f5-6293-4846-badd-56a29c70880d)
- [EEA current air-quality download/API application](https://eeadmz1-downloads-webapp.azurewebsites.net/)
- [EEA European Air Quality Index](https://airindex.eea.europa.eu/AQI/index.html)
- [EEA up-to-date air-quality viewer](https://discomap.eea.europa.eu/Map/UTDViewer/UTDViewer/)
- [EEA monitoring-station ArcGIS service](https://air.discomap.eea.europa.eu/arcgis/rest/services/AirQuality/AirQualityDownloadServiceEUMonitoringStations/MapServer/0)
- [CAMS European air-quality reanalysis](https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-reanalyses?tab=overview)
- [CAMS European air-quality forecast](https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts?tab=overview)
- [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api)
- [CAMS European air-quality forecast plots](https://atmosphere.copernicus.eu/european-air-quality-forecast-plots)
- [World Health Organization hot-weather advice](https://www.who.int/europe/publications/health-advice-for-hot-weather)
