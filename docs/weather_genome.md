# Weather Genome

Implementation specification for a versioned atlas of recurring atmospheric
states over the North Atlantic and Europe, connected to their historical
weather expression in Debrecen.

**Status:** proposed, researched, ready for phased implementation  
**Scope:** Debrecen and its upstream large-scale circulation only  
**Primary home:** Archive  
**Last researched:** 2026-08-22

## 1. Product decision

Weather Genome should not be a decorative cluster diagram or another name for
the existing analog search. It should be a stable, inspectable coordinate
system for the atmosphere: every historical day is assigned to one node in a
small map of recurring circulation patterns, and every node is connected to the
weather that historically accompanied it in Debrecen.

The product should ship in two explicitly different layers:

1. **Surface Phenotypes** use the local daily ERA5 variables Atlas already
   caches. They answer, "What kinds of days recur in Debrecen?" This is a
   no-new-secret MVP, but it must never be called a circulation classification.
2. **Circulation Genome** uses regional geopotential-height anomalies from a
   consistent reanalysis. It answers, "What large-scale atmospheric state was
   present, and how does Debrecen usually respond to that state?" This is the
   intended flagship.

The two layers may share a page and interaction model, but must not share node
identifiers or be visually conflated. A cold, windy local phenotype can occur
under more than one circulation state; that ambiguity is scientifically useful.

### Recommended launch form

- Use a frozen 12-node circulation map as the canonical first edition.
- Train on daily 500 hPa geopotential-height anomalies for 1991-2020.
- Use a North Atlantic-European domain broad enough to retain upstream
  circulation, initially 30-75 degrees N and 50 degrees W-50 degrees E at 1
  degree spacing.
- Assign later dates to the frozen map without retraining it.
- Show the current 72-hour period as a three-day path through the node map.
- Show local outcomes as seasonal distributions, not single deterministic
  promises.
- Keep the numerical node ID canonical. Human-readable names are editorial
  annotations and may evolve only in a versioned release.

The node count and domain are starting hypotheses, not truths. Section 8 defines
the tests that must pass before they become the v1 model.

## 2. What the feature should let a reader do

A visitor should be able to answer all of these questions without meteorology
training:

- Which recurring circulation state best matches each of the last three days?
- Was the match typical for that node or far from anything in the reference set?
- Is this state common in August, or unusual for the season?
- How long does it usually persist, and which states usually follow it?
- During this state, what distributions of temperature, precipitation, wind,
  sunshine, soil-water balance, and renewable-weather yield have historically
  occurred in Debrecen?
- Which past dates were the clearest examples of this state?
- Has its observed frequency changed between reference periods?
- What is directly supplied by reanalysis, and what did Atlas derive?

For an expert, the same interface should expose composite fields, anomaly
definitions, sample size, within-node spread, assignment distance, transition
counts, and downloadable data.

## 3. Non-goals and language rules

Weather Genome is not:

- a forecast or warning system;
- a claim that the atmosphere has exactly 12 natural categories;
- an official weather-regime catalogue;
- a causal model of Debrecen weather;
- a replacement for the current date-level historical analog engine;
- a classifier of fronts, cyclones, blocking, or air masses unless those labels
  are independently derived and supported;
- evidence that a change in node frequency is attributable to climate change;
- a live model that silently changes every time new data arrives.

Use "associated with", "historically accompanied by", and "assigned to".
Avoid "caused", "will produce", and "this is the same weather". A node is an
approximation in a continuous atmospheric state space.

## 4. Evidence model

Every value published by this feature must carry one of Atlas's existing
evidence labels:

| Label | Weather Genome use |
|---|---|
| Model-derived | ERA5 or another reanalysis field; a model-constrained reconstruction, not a direct observation |
| Observed | HungaroMet station outcomes associated with nodes, where coverage is sufficient |
| Derived | Anomalies, PCA coordinates, SOM nodes, distances, composites, transition rates, and local distributions |
| Remote-sensed | Radar, lightning, or satellite event summaries joined to node dates; optional after v1 |

The page header must state: "A fixed statistical map of recurring reanalysis
patterns. Nodes are Atlas-derived categories, not forecasts or official weather
regimes."

## 5. Data required

### 5.1 Canonical circulation input

| Field | Role | Temporal treatment | Spatial treatment | Required in v1 |
|---|---|---|---|---|
| 500 hPa geopotential or geopotential height | Defines the primary circulation pattern | Daily mean from a consistent set of synoptic hours | Regrid to 1 degree, crop to the versioned domain | Yes |
| Mean sea-level pressure | Interpretable surface composite and sensitivity experiment | Daily mean | Same grid/domain | Composite; candidate training field |
| 850 hPa temperature | Air-mass and thermal-advection context | Daily mean | Same grid/domain | Composite only |
| 700 hPa relative humidity | Moisture context | Daily mean | Same grid/domain | Optional composite |
| 300 hPa wind speed | Jet context | Daily mean | Same grid/domain | Optional composite |

The canonical v1 model should be trained on one field, 500 hPa height anomaly,
unless validation demonstrates a material and stable improvement from a coupled
field model. Starting with one field keeps distance units and node meaning
legible. The other fields explain nodes after assignment.

If the provider supplies geopotential in square metres per square second,
convert it to geopotential height with `height_m = geopotential / 9.80665`.
Persist the original units, conversion, and constant in the manifest.

### 5.2 Local outcome variables

The following already exist in, or can be derived from, Atlas's daily pipeline.
They are joined by local calendar date after circulation assignment.

| Family | Variables and summaries |
|---|---|
| Temperature | mean, minimum, maximum, diurnal range, standard-normal anomaly, percentile |
| Moisture | dew point, relative humidity, vapour-pressure deficit, fog/low-visibility evidence |
| Precipitation | total, wet-day probability, rain/snow split, rolling water balance |
| Wind | mean and maximum 10 m wind, gust, 100 m wind, direction sectors |
| Radiation | shortwave, direct, diffuse, sunshine duration, cloud cover |
| Land | ET0, soil temperature, soil moisture, 7/30/90-day water balance |
| Events | objective Atlas event flags and frontal-passage evidence |
| Energy weather | physical PV and wind reference yields and the normalized climate index |
| Station checks | Debrecen Airport 10-minute observations aggregated to daily values |

Outcomes must be conditioned by calendar season or month. Otherwise, a node
that is common in winter will appear to "produce" low temperature merely
because of seasonality. The interface should default to the selected date's
meteorological season and allow an all-season view with an explicit warning.

### 5.3 Surface Phenotype MVP input

The no-new-provider MVP can use these standardized local daily features:

```text
temperature_mean anomaly
temperature diurnal range
dew_point_mean anomaly
precipitation_total transformed as log1p(x)
mean_sea_level_pressure anomaly
wind_speed_10m_mean
wind_direction encoded as sin(direction), cos(direction)
shortwave_radiation anomaly
cloud_cover_mean
ET0
soil_moisture_0_to_7cm anomaly
```

Each continuous feature is standardized using training-period statistics.
Missing land variables must not silently reduce the feature vector. Either use
a declared reduced model version or mark the day unassigned.

### 5.4 Temporal keys

- Store source timestamps in UTC.
- Derive `local_date` using `Europe/Budapest`, including daylight-saving time.
- A circulation day is the UTC day represented by the regional daily mean.
- A Debrecen outcome day is the local civil day.
- The manifest must record this deliberate alignment. A sensitivity test must
  compare it with a 06-06 UTC or 12 UTC definition before v1 is frozen.
- Leap day receives its own assignments but its climatological anomaly baseline
  should be interpolated from adjacent calendar days unless the reference
  sample is demonstrably sufficient.

## 6. Source and API plan

### 6.1 Recommended primary source: ARCO-ERA5 on Google Cloud

Google's Analysis-Ready, Cloud-Optimized ERA5 copy can be accessed as public
Zarr and therefore preserves Atlas's no-repository-secret property. It is the
preferred source for the one-time circulation bootstrap because a regional,
multi-decade pressure-level subset is much more efficient to select from Zarr
than thousands of daily REST requests.

Illustrative access pattern:

```python
import xarray as xr

dataset = xr.open_zarr(
    "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3",
    chunks=None,
    storage_options={"token": "anon"},
)

# Resolve the exact variable and coordinate names from dataset metadata first.
# Then select only the versioned time range, pressure level, and domain.
```

Implementation requirements:

- inspect and log coordinate order, longitude convention, units, chunk layout,
  and dataset metadata before selection;
- convert 0-360 longitude to the documented Atlas convention exactly once;
- select only needed pressure levels, variables, times, and the regional box;
- write annual or monthly immutable regional subsets to the raw cache;
- never execute the complete multi-decade bootstrap in the routine 30-minute
  Pages job;
- record object path, access date, selected coordinates, and a digest of every
  derived immutable file;
- test cloud egress and memory on a single month before requesting the full
  period.

ARCO's README documents anonymous Zarr access and the coverage of its ERA5 copy.
Google's public-dataset documentation explains that public objects may be read
without a Google account, while normal network and egress constraints still
apply.

### 6.2 Authoritative alternative: Copernicus Climate Data Store

The CDS ERA5 pressure-level dataset is the authoritative source and covers
hourly data from 1940 onward. It requires a CDS account, acceptance of the
applicable terms, and a personal API token. This makes it suitable for a manual
bootstrap or a protected workflow, but adopting it in scheduled CI would change
the README statement that Atlas requires no repository secret.

The robust integration pattern is:

```python
import cdsapi

client = cdsapi.Client()
request = {
    # Paste the selection generated by "Show API request" on the current
    # dataset form, then preserve a redacted copy in the bootstrap manifest.
}
client.retrieve(
    "reanalysis-era5-pressure-levels",
    request,
    "era5-pressure-levels-subset.grib",
)
```

The CDS request schema should be generated from the dataset page at
implementation time rather than copied permanently into this specification;
dataset-form names and delivery options can change. A bootstrap command must
validate the downloaded GRIB/NetCDF metadata before accepting it. Never commit
the token, `.cdsapirc`, or a request containing credentials.

### 6.3 Existing Open-Meteo sources

Atlas should continue using Open-Meteo's Historical Weather API for local ERA5
outcomes and the Surface Phenotype MVP. The current annual cache can be extended
rather than duplicated.

The Historical Forecast API is appropriate for displaying the current
pressure-level sequence and assigning recent days when its fields match the
frozen model's preprocessing. It is not suitable as the multi-decade training
archive: its coverage begins around 2021/2022 and model versions change over
time. The UI and model manifest must not imply that short historical-forecast
coverage is a climate reference.

Example shape for existing local history:

```text
GET https://archive-api.open-meteo.com/v1/archive
    ?latitude=47.5316
    &longitude=21.6273
    &start_date=1991-01-01
    &end_date=1991-12-31
    &daily=temperature_2m_mean,precipitation_sum,
           wind_speed_10m_mean,mean_sea_level_pressure_mean,
           shortwave_radiation_sum,et0_fao_evapotranspiration
    &models=era5
    &timezone=Europe%2FBudapest
```

Use Atlas's existing request builder rather than creating a second HTTP client.
The exact supported daily variable names must be checked against the provider
schema during implementation.

### 6.4 Prototype-only fallback: NCEP/NCAR Reanalysis 1

NOAA PSL exposes the NCEP/NCAR Reanalysis through files and THREDDS without
authentication. Its coarse 2.5 degree grid and older assimilation system can be
useful for a disposable method prototype. It must not become the operational
v1 source: NOAA states that production of this dataset stopped on 17 March
2026. It therefore cannot provide a continuing assignment stream.

### 6.5 Source decision matrix

| Source | Auth | Coverage/use | Strength | Constraint | Decision |
|---|---|---|---|---|---|
| ARCO-ERA5 | Anonymous public cloud read | Multi-decade regional training and frozen reference | Efficient Zarr subsetting; no Atlas secret | Network/chunk/egress testing required | Preferred bootstrap |
| CDS ERA5 pressure levels | CDS account and token | Authoritative bootstrap and audit | Official dataset and terms | Secret and queued delivery | Supported alternative |
| Open-Meteo Historical Weather | No key for current use | Local daily outcomes and phenotype MVP | Already integrated and cached | Point fields, not full circulation archive | Required |
| Open-Meteo Historical Forecast | No key for current use | Recent pressure fields/current assignment | Already integrated | Short, model-changing archive | Operational recent input only |
| NCEP/NCAR R1 | None | Method prototype | Simple and long historical record | Coarse and discontinued in 2026 | Never production |

No source may be substituted automatically for the canonical training source.
A source change creates a new model version because interpolation, bias, and
assimilation differences can move node boundaries.

## 7. Scientific method

### 7.1 Training reference

- **Reference period:** 1991-2020, aligned with Atlas's WMO standard normal.
- **Assignment period:** all available dates outside the reference period may
  be mapped to the frozen model.
- **Seasonality:** one year-round model trained on calendar-day anomalies is the
  recommended starting point. It supports transitions across seasons and a
  single stable visual geography.
- **Sensitivity run:** compare four seasonal models. Use them only if the
  year-round map performs poorly or creates nodes dominated by residual season.

The use of 1991-2020 does not imply that those years contain every possible
future state. Out-of-map distance exists precisely to expose novel or poorly
represented days.

### 7.2 Daily field preparation

For each date:

1. Read the selected 500 hPa hourly or synoptic-time fields.
2. Reject a day if required time steps or more than the permitted spatial
   fraction are missing.
3. Calculate a daily mean using a fixed set of UTC hours and record that set.
4. Convert units and normalize longitude/latitude ordering.
5. Regrid to the fixed 1 degree target grid using a documented method.
6. Calculate a calendar-day climatology at each cell from 1991-2020.
7. Smooth that climatology cyclically with an odd, versioned window. Start with
   31 days; include 15 and 61 days in the sensitivity experiment.
8. Subtract the smoothed climatology to obtain the height anomaly.
9. Multiply every latitude row by `sqrt(cos(latitude))` before distance
   calculations so densely spaced polar grid cells do not dominate.
10. Flatten cells in a fixed coordinate order.

The preprocessing model consists of the target coordinates, climatology field,
missing-data mask, area weights, feature mean, and any dimensionality reduction.
These objects are part of the model, not regenerable presentation details.

### 7.3 Dimensionality reduction

Two candidates must be evaluated:

- **Direct weighted grid vectors:** maximally interpretable and avoids another
  learned transform; computationally larger.
- **Deterministic PCA:** fit only on training data, retain the number of
  components needed for 90-95% variance, and run the SOM in standardized score
  space. Persist the feature mean, singular vectors, explained variance, and
  sign convention.

PCA is recommended if it materially improves training time and seed stability.
It must not be fitted on assignment/hold-out years. Since singular-vector signs
can flip without changing the solution, version comparisons must align signs
before declaring a model changed.

### 7.4 Self-organizing map

A self-organizing map (SOM) is recommended because its two-dimensional lattice
preserves approximate neighbourhoods: adjacent nodes should represent more
similar fields than distant nodes. This makes a genuine "genome map" possible.

Candidate grids:

```text
3 x 3  =  9 nodes
4 x 3  = 12 nodes, recommended initial candidate
5 x 4  = 20 nodes
```

Test rectangular and hexagonal neighbourhoods. A hexagonal neighbourhood has
more uniform adjacency and is supported by recent circulation-regime work, but
the published page may use visually rectangular cards if accessibility and
mobile navigation are substantially better. Visual layout and mathematical
neighbourhood must never be confused in metadata.

The implementation may use the small MIT-licensed MiniSom package, pinned to a
reviewed version, or a compact batch SOM maintained in Atlas. Regardless of
library, serialize numeric arrays and JSON metadata rather than a Python pickle.
Set and publish the random seed, initialization method, learning schedule,
neighbourhood function, iteration count, and library version.

### 7.5 Assignment and confidence

For every day, store:

- best matching unit (`node_id`);
- Euclidean distance to the best matching unit in the trained feature space;
- distance to the second-best unit;
- distance percentile relative to training days assigned to that node;
- margin between first and second match;
- `out_of_map` when distance exceeds the versioned training threshold;
- previous and next assigned node where available;
- current run length of the same node;
- source and preprocessing completeness.

The public confidence label should describe representativeness, not forecast
confidence:

| Label | Suggested rule | Public meaning |
|---|---|---|
| Characteristic | node-specific distance <= 50th training percentile | Close to many reference examples |
| Typical | > 50th and <= 90th percentile | Within the normal spread of the node |
| Peripheral | > 90th and <= 99th percentile | Assigned, but unlike most examples |
| Outside reference | > 99th percentile or fails an absolute guard | No node is a good match |

Thresholds are provisional until calibrated. Never label a distant assignment
"extreme weather"; it is extreme only in model distance.

### 7.6 Node summaries

For each node and season, calculate:

- occurrence count and share, with a Wilson or bootstrap interval;
- composite and within-node standard deviation for all circulation fields;
- median, interquartile range, and 10th/90th percentiles of local outcomes;
- wet-day probability and event frequencies with denominators;
- median persistence and the full run-length distribution;
- inbound and outbound transition counts and conditional probabilities;
- strongest characteristic dates (smallest distances);
- peripheral dates (largest valid distances);
- calendar-month distribution;
- comparison of node frequency across declared eras.

Frequency comparisons should report counts, exposure years, uncertainty, and a
multiple-testing-aware significance method. A visual difference is not by
itself a trend. Transition probabilities need minimum count rules and should
prefer credible intervals to false precision.

### 7.7 Node names

Node IDs use stable machine labels such as `G01` through `G12`. A meteorologist
may add names after inspecting composites, for example "Atlantic trough west"
or "continental ridge", but names must:

- describe the composite, not infer impact;
- avoid official regime terminology unless the pattern is quantitatively
  matched to that regime definition;
- live in a versioned editorial JSON file;
- include a one-sentence rationale;
- never be regenerated automatically in the daily build.

## 8. Model selection and validation

Do not select the prettiest grid. Produce a validation report for every
candidate domain, node count, anomaly window, PCA choice, and seed family.

### 8.1 Quantitative tests

| Test | Purpose | Acceptance direction |
|---|---|---|
| Quantization error | Average distance from days to their node | Lower, balanced against complexity |
| Topographic error | Whether first and second matches are neighbours | Lower |
| Occupancy | Avoid empty or tiny nodes | No empty nodes; define and justify a minimum seasonal sample |
| Seed stability | Whether independent starts recover equivalent patterns | High after optimal node alignment |
| Bootstrap stability | Whether resampled years preserve node structure | High, with uncertainty shown |
| Hold-out distance | Generalization to years after 2020 | Comparable to training after known climate shift is considered |
| Residual seasonality | Whether anomalies still separate mostly by month | Low unless physically interpretable |
| Neighbour coherence | Whether adjacent prototypes are more alike | Better than shuffled layouts |
| Outcome separation | Whether nodes distinguish Debrecen distributions | Useful but never optimized at the expense of circulation fidelity |

When comparing runs, align nodes with a minimum-cost assignment before measuring
stability. Node number alone has no cross-run identity.

### 8.2 Physical review

An expert review checklist must confirm:

- composite contours are meteorologically plausible;
- gradients and anomaly signs are not artifacts of longitude reversal or unit
  conversion;
- edge nodes are not just missing-data patterns;
- each human name matches the composite at more than one pressure level;
- the current Atlas synoptic plots tell a consistent story for sampled dates;
- the broad-domain result is not dominated by grid-area weighting;
- Debrecen outcome differences persist after conditioning on season;
- no node is described deterministically from a noisy outcome distribution.

### 8.3 Reproducibility test

A clean bootstrap using the same manifest must reproduce:

- raw-subset digests or an explicitly documented provider revision;
- target coordinate arrays;
- training date list;
- climatology and PCA digests;
- node prototype arrays within a declared numeric tolerance;
- every training assignment after aligned node labelling;
- published JSON schema and representative page snapshots.

## 9. Data contracts and storage

### 9.1 Model manifest

Proposed `weather_genome_manifest.json`:

```json
{
  "schema_version": "1.0.0",
  "model_id": "wg-z500-1991-2020-v1",
  "created_at_utc": "2026-08-22T00:00:00Z",
  "source": {
    "provider": "ARCO-ERA5",
    "dataset_uri": "provider object recorded at bootstrap",
    "retrieved_at_utc": "...",
    "licence_notice": "Contains modified Copernicus Climate Change Service information"
  },
  "reference_period": [1991, 2020],
  "daily_hours_utc": [0, 6, 12, 18],
  "field": "geopotential_500hPa",
  "units_in": "m2 s-2",
  "units_model": "m",
  "domain": {"south": 30, "north": 75, "west": -50, "east": 50, "step": 1.0},
  "climatology": {"method": "calendar_day_cyclic_mean", "window_days": 31},
  "area_weight": "sqrt_cos_latitude",
  "reduction": {"method": "pca", "variance_target": 0.95},
  "som": {"rows": 3, "columns": 4, "topology": "hexagonal", "seed": 42},
  "digests": {}
}
```

The real manifest must include package versions, exact variable metadata,
missing-data rules, training and excluded dates, iteration settings, licence
text, and file digests.

### 9.2 Assignment table

`weather_genome_assignments.parquet` is the canonical analytical table. Publish
a smaller CSV or JSON projection for the static site.

| Column | Type | Meaning |
|---|---|---|
| date_utc | date | Circulation day |
| local_date | date | Debrecen outcome join date |
| model_id | string | Frozen model identity |
| node_id | string | Canonical node |
| best_distance | float | Distance in declared model space |
| second_distance | float | Runner-up distance |
| distance_percentile | float | Node-conditional training percentile |
| match_class | enum | characteristic, typical, peripheral, outside_reference |
| out_of_map | boolean | Explicit novelty flag |
| run_length | integer | Consecutive days in this node through this date |
| source_complete | boolean | All required source data present |
| assigned_at_utc | timestamp | Provenance |

### 9.3 Node and transition products

```text
data/reference/weather_genome/<model_id>/
  manifest.json
  target_grid.npz
  climatology.npz
  transform.npz
  prototypes.npz
  node_labels.json
  validation.json
  validation_report.html

data/processed/
  weather_genome_assignments.parquet
  weather_genome_node_statistics.parquet
  weather_genome_transitions.parquet
  weather_genome_current.json

site/archive/data/weather-genome/
  manifest.json
  current.json
  nodes.json
  transitions.json
  assignments-by-year/*.json
```

Raw multi-decade regional fields belong in the ignored cache or a versioned
external artifact, not the Git repository. The small frozen model, manifest,
validation summary, and published derived statistics should be committed so a
daily assignment does not retrain the model.

### 9.4 Configuration

Proposed additive configuration:

```yaml
weather_genome:
  enabled: true
  required: false
  model_id: wg-z500-1991-2020-v1
  model_directory: data/reference/weather_genome/wg-z500-1991-2020-v1
  current_assignment_source: historical_forecast
  outside_reference_percentile: 0.99
  publish_surface_phenotypes: true
```

Training configuration belongs in a separate frozen model recipe, not in the
daily operational YAML. Changing a model recipe must be an explicit release.

## 10. Software architecture

### 10.1 New modules

| Module | Responsibility |
|---|---|
| `atlas/genome_ingest.py` | Bootstrap and validate regional reanalysis subsets |
| `atlas/genome_preprocess.py` | Daily means, units, grid, anomalies, weights, PCA |
| `atlas/genome_model.py` | Train, align, validate, serialize, and assign SOM nodes |
| `atlas/genome_outcomes.py` | Join assignments to local daily outcomes and calculate seasonal summaries |
| `atlas/genome_plots.py` | Lattice, composites, distributions, paths, and transitions |
| `atlas/genome.py` | Typed orchestration models consumed by the report pipeline |

Avoid adding this logic to `climatology.py` or `synoptic.py`; those modules are
inputs, while the frozen model has a separate lifecycle.

### 10.2 Commands

Proposed commands:

```powershell
atlas-genome inspect-source --source arco-era5
atlas-genome bootstrap --recipe configs/genome-v1.yml
atlas-genome train --recipe configs/genome-v1.yml
atlas-genome validate --model wg-z500-1991-2020-v1
atlas-genome assign --model wg-z500-1991-2020-v1 --start 2026-08-19 --end 2026-08-21
atlas-genome export-site --model wg-z500-1991-2020-v1
```

They may be subcommands of `atlas`; the important boundary is operational:
bootstrap and train are manual/release jobs, while assignment and export are
safe in the daily pipeline.

### 10.3 Daily pipeline integration

```text
existing recent synoptic fields
             |
             v
apply frozen preprocessing -> assign each complete day -> current.json
             |                                      |
             |                                      v
             +------------------------> analysis overview card
historical assignment store ---------> archive Weather Genome page
local daily metrics -----------------> seasonal node outcome summaries
```

If required regional fields are missing, the whole Atlas report must still
publish. Show "Genome assignment unavailable" with the source date and reason.
Never fall back to Surface Phenotypes while retaining the Circulation Genome
label.

## 11. UI and interaction specification

### 11.1 Information architecture

- Add **Weather Genome** to the Archive family, alongside Climate Summary,
  Record Book, Weather Event Index, and Report Archive.
- Publish at `site/archive/weather-genome.html`.
- Add a compact current-state card to the 72-Hour Analysis overview and Climate
  & Analogs page. It links into the archive with the current nodes selected.
- Keep the full explorer out of the Daily Report. A single sentence may say,
  "This day mapped to G07, a typical match," with a link.

This placement expresses the product correctly: a stable historical reference
that helps interpret the current period.

### 11.2 Page anatomy

1. **State strip** - model version, reference period, latest assigned date,
   evidence label, and data-integrity state.
2. **Plain-language introduction** - two sentences explaining that nodes are a
   statistical simplification of continuous circulation.
3. **Current path** - three dated steps, transition arrows, match classes, and
   one concise interpretation.
4. **Genome lattice** - 12 keyboard-focusable node cards arranged according to
   the trained topology.
5. **Selected node dossier** - composite map, local distributions, seasonality,
   persistence, transitions, and characteristic dates.
6. **Compare states** - optional side-by-side comparison of two nodes.
7. **Frequency through time** - carefully qualified era/rolling-frequency view.
8. **Methods and evidence** - model card, validation, source links, licences,
   and downloads.

### 11.3 Genome lattice

Each node card includes:

- canonical ID and short editorial name;
- a small 500 hPa anomaly composite with one shared symmetric colour scale;
- reference frequency for the active season;
- median persistence;
- current marker when selected by the 72-hour path;
- a text pattern such as `ridge +`, `near neutral`, or `trough -` so colour is
  never the sole carrier of meaning.

Do not size cards by frequency because it destroys the learned topology. Use a
small bar or number. On narrow screens, render a numbered list in mathematical
neighbour order and provide "neighbours" links within each dossier.

Keyboard behaviour should implement a labelled grid: arrow keys move to
mathematical neighbours, Enter opens the dossier, and Escape returns focus to
the active card. If the mathematical topology is hexagonal, document diagonal
neighbour movement for assistive technology rather than relying on position.

### 11.4 Controls and URL state

| Control | Default | URL parameter |
|---|---|---|
| Layer | circulation | `layer=circulation` |
| Season | selected date's season | `season=JJA` |
| Node | current/latest node | `node=G07` |
| Outcome | temperature anomaly | `outcome=tmean_anomaly` |
| Era | 1991-2020 | `era=1991-2020` |
| Compare node | none | `compare=G03` |
| Date lookup | none | `date=2026-08-21` |

State changes update the query string without a full reload, and reloading or
sharing the URL restores the same view. Validate every parameter against a
published allow-list.

### 11.5 Node dossier

The dossier should lead with interpretation, then evidence:

```text
G07 / Central-European ridge
Most characteristic in late summer. In JJA reference cases, Debrecen was warmer
than its calendar normal in 68% of assigned days, but outcomes ranged widely.
The selected 2026-08-21 field is a peripheral match (94th distance percentile).
```

Required panels:

- composite 500 hPa anomaly with optional MSLP, T850, humidity, and jet layers;
- selected Debrecen outcome distribution with median, interval, sample size,
  and the current date marker;
- occurrence by month;
- persistence distribution;
- top inbound and outbound transitions with counts and denominators;
- five most characteristic historical dates linking to available archived
  reports;
- within-node spread or uncertainty, not only a smooth composite;
- source and derivation details immediately accessible from an info control.

A map must use a consistent projection, bounds, contour interval, zero line,
and colour scale across nodes. Comparing maps with auto-scaled colours would be
misleading.

### 11.6 Frequency and change view

Offer fixed-period comparisons only when coverage is homogeneous. Recommended:

- 1961-1990 if the canonical source and preprocessing cover it consistently;
- 1991-2020 reference;
- 2001-2020 and 2006-2025 as clearly labelled overlapping descriptive windows;
- a 10-year centred or trailing frequency with uncertainty.

The copy must state that the node prototypes are fixed from 1991-2020 and older
or newer days are assigned to them. Show missing years and out-of-map rate. Do
not imply that frequency differences alone establish attribution or a future
trend.

### 11.7 Visual and accessibility rules

- Use Atlas's typography, evidence badges, publication-state strip, plot info
  controls, and archive breadcrumbs.
- All maps and charts need a concise text summary and a downloadable table.
- Use a colour-vision-deficiency-safe diverging scale centred exactly at zero.
- Pair colour with contour labels, signs, patterns, or text.
- Respect `prefers-reduced-motion`; the current path should step, not animate,
  when reduction is requested.
- Do not autoplay transitions.
- Provide a static table of node statistics before or after interactive plots.
- Keep mobile Plotly payloads bounded by lazy-loading dossiers rather than
  embedding every full-resolution field at first paint.

## 12. Existing examples and what to borrow

These are design and method precedents, not templates to clone.

| Example | Useful idea | What Atlas should do differently |
|---|---|---|
| European winter circulation SOM study | A compact 12-node map of Z500 anomalies and local-impact analysis | Run year-round validation and publish operational assignments |
| 2026 JGR hexagonal SOM study | Hex topology, anomaly preprocessing, transition analysis | Add a public model card and Debrecen-specific evidence |
| Euro-Mediterranean multivariate SOM study | Coupled SLP/Z700/moisture patterns | Begin with one canonical field until coupled-field value is proven |
| Weather-whiplash SOM study | All-month nodes and changing transition behaviour | Avoid event attribution and expose raw counts/uncertainty |
| IPCC Interactive Atlas | Persistent selectors, regional context, methodological guidance | Keep the page much narrower and tied to individual dates |
| Copernicus Interactive Climate Atlas | Layer controls and provenance near the visualization | Make the fixed model/version more prominent |
| Atlas Climate & Analogs | Existing seasonal normals, analog links, evidence vocabulary | Separate date-neighbour search from state-space classification |

The core research precedent is the use of SOMs to organize daily geopotential
height anomaly fields into a topology that can be related to local weather.
Research choices vary substantially in domain, season, fields, node count, and
anomaly calculation, which is why Atlas must publish a sensitivity and stability
report rather than cite one paper as a universal recipe.

## 13. Performance, cost, and operations

### Bootstrap budget

Before a complete pull, estimate from a one-month sample:

- compressed and expanded bytes per field/year;
- Zarr chunks touched by the regional selection;
- download and preprocessing time;
- peak resident memory;
- GitHub Actions cache size if any;
- cost/egress risk of the selected public-cloud path.

The bootstrap should be resumable by immutable month or year. A completed shard
is accepted only after metadata validation and checksum. Partial files get a
temporary suffix and are never read by training.

### Daily budget

The operational assignment should add seconds, not minutes, to a normal Atlas
build. Load the small frozen transform and prototypes, preprocess at most three
days, append idempotently to assignments, update the current JSON, and rebuild
only the explorer's lightweight year index. Historical composites do not need
daily recomputation unless an assignment was added.

### Browser budget

- initial HTML plus JSON target below 500 KB compressed where practical;
- load full composite arrays only when a node is opened;
- cache immutable model assets with a model-version path;
- use simplified map geometry and precomputed contours/images for the lattice;
- retain CSV/JSON downloads even if interactive Plotly fails.

## 14. Failure states

| Failure | Behaviour |
|---|---|
| Current regional data absent | Publish Atlas; show assignment unavailable and exact missing period |
| Frozen model file/digest invalid | Do not assign; fail the Genome component loudly, never retrain |
| Source switches units or coordinate order | Reject during validation |
| Assignment is outside reference | Show the nearest node plus prominent outside-reference status, or show unassigned if absolute guard fails |
| Local outcome history incomplete | Keep circulation node; suppress affected outcome and show denominator/coverage |
| Node asset fails in browser | Render text/table fallback |
| Provider revises historical input | Preserve current model; investigate and release a new version rather than mutate history |

## 15. Tests

### Unit tests

- longitude conversion and monotonically ordered coordinates;
- geopotential-to-height conversion and unit rejection;
- fixed UTC daily mean with missing synoptic hours;
- leap-day climatology and cyclic smoothing across 31 December;
- latitude weights at the equator and high latitudes;
- deterministic PCA and SOM with a fixture dataset;
- node-alignment algorithm across permuted prototypes;
- distance percentile and out-of-map boundary cases;
- transition/run-length logic at gaps and year boundaries;
- seasonal outcome joins across Budapest daylight-saving changes;
- JSON schema, digests, and model-version compatibility.

### Integration tests

- one small public-source subset from fetch through assignment;
- frozen fixture model produces known node assignments;
- Surface Phenotype and Circulation Genome IDs cannot mix;
- optional component failure does not block the core report;
- current 72-hour path links to valid archive URL state;
- site builds offline from cached derived products.

### UI tests

- complete keyboard operation of the lattice and dossier;
- mobile list fallback and no horizontal page overflow;
- visible focus and reduced-motion behaviour;
- text summaries reflect active controls;
- identical scales across composite maps;
- empty, peripheral, out-of-map, and stale-data states;
- page remains useful without JavaScript.

### Scientific regression tests

- reference-period cell anomalies average approximately zero by calendar date;
- all node prototypes have declared units and shape;
- no empty node and no unexplained extremely small seasonal occupancy;
- neighbouring prototypes are closer on average than non-neighbours;
- station outcome sample counts reproduce direct joins;
- published frequencies sum correctly after unassigned days are excluded;
- a model update produces an explicit old/new alignment and change report.

## 16. Rollout plan and acceptance gates

### Phase 0 - research fixture

Build a one-year, coarse-grid offline fixture. Prove coordinate handling,
anomalies, training, serialization, and the page skeleton.

**Gate:** deterministic rerun; physically recognizable composites; no daily
pipeline changes.

### Phase 1 - Surface Phenotypes

Train and publish a clearly labelled local-day map from the existing immutable
ERA5 cache. This validates interaction, URLs, assignments, distributions, and
archive integration with no new provider.

**Gate:** users cannot mistake it for circulation; seasonal conditioning and
missing-data behavior pass review.

### Phase 2 - Circulation bootstrap and model bake-off

Acquire the complete regional reference, train all candidate models, publish an
internal validation report, and select v1 against the criteria in Section 8.

**Gate:** source licence and provenance complete; model stable across seeds and
bootstrap years; expert physical review signed off.

### Phase 3 - Archive explorer

Publish the frozen lattice, node dossiers, date lookup, transition summaries,
outcome distributions, methods, and downloads.

**Gate:** static-site performance and accessibility pass; all visual claims have
denominators and a table fallback.

### Phase 4 - Current 72-hour path

Assign recent complete days using a field compatible with the frozen
preprocessing and add concise cards to the analysis.

**Gate:** recent-input consistency is quantified against canonical ERA5 for an
overlap period. If provider/model differences produce unstable nodes, delay this
phase or label the assignment source separately.

### Phase 5 - Deep archive links and comparisons

Link characteristic dates to preserved Atlas reports, add carefully qualified
era comparisons, and optionally join event/radar evidence.

**Gate:** no broken date links, no heterogeneous-coverage trend claim, and no
material first-load regression.

## 17. Definition of done for v1

Weather Genome v1 is complete only when:

- a frozen, versioned model and source manifest are committed;
- the full training and validation report is reproducible;
- every complete assignment includes distance and match class;
- current dates can be assigned without training or a secret in routine CI;
- node outcome summaries are seasonal and include sample sizes;
- the archive explorer works by keyboard and on a narrow mobile viewport;
- maps share fixed scales and have equivalent text/table content;
- data gaps and out-of-map states are visible;
- pages include source, licence, method, and model-version disclosures;
- offline tests cover the scientific transforms and report smoke path;
- the README and `docs/data_sources.md` describe the new source and limits.

## 18. Source register

Primary and scientific sources consulted for this specification, accessed
2026-08-22:

- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- [Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api)
- [Copernicus ERA5 hourly data on pressure levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-pressure-levels)
- [How to use the CDS API](https://cds.climate.copernicus.eu/en/how-to-api)
- [ARCO-ERA5 repository and access examples](https://github.com/google-research/arco-era5)
- [Google Cloud public datasets](https://cloud.google.com/storage/docs/public-datasets)
- [NOAA PSL NCEP/NCAR Reanalysis 1](https://psl.noaa.gov/data/gridded/data.ncep.reanalysis.html)
- [NOAA PSL NCEP/NCAR THREDDS catalogue](https://www.psl.noaa.gov/thredds/catalog/Datasets/ncep.reanalysis/catalog.html)
- [Using self-organizing maps to classify European winter circulation and local impacts](https://pmc.ncbi.nlm.nih.gov/articles/PMC6988488/)
- [Hexagonal SOM analysis of atmospheric circulation, JGR Atmospheres (2026)](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2025JD044874)
- [Multivariate self-organizing maps of Euro-Mediterranean circulation](https://journals.ametsoc.org/view/journals/clim/24/13/2011jcli3622.1.xml)
- [SOM circulation types and weather-whiplash transitions](https://www.nature.com/articles/s41612-023-00542-9)
- [Year-round European circulation regimes and heat extremes](https://esd.copernicus.org/articles/17/265/2026/)
- [MiniSom reference implementation](https://github.com/JustGlowing/minisom)
- [IPCC Interactive Atlas guidance](https://interactive-atlas.ipcc.ch/regional-information/guidance)
- [Copernicus Interactive Climate Atlas](https://atlas.climate.copernicus.eu/)
