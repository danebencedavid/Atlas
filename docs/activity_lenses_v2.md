# Activity Lenses: methodology 2

## Evidence flow and the first implementation boundary

The live pipeline requests hourly Open-Meteo Historical Weather API data, selects
the completed local day, and passes that frame to the activity engine. This is
gridded historical weather (the provider's default best-match product), not the
separate HungaroMet station observations. Demo builds use synthetic weather.

Previously, unique timestamps were counted as hours; numeric aggregation discarded
missing values; the energy index replaced invalid ratios with 50; supplemental
facts assigned full coverage to any finite number. PV computation also fills some
missing model inputs with zero. Standard-normal aggregation can sum missing
radiation into zero. These are distinct ways that dependency validity disappears.

The evidence boundary aligns to the exact expected hourly UTC timestamps
between local midnights, preserving 23/25-hour DST days. Off-grid rows are excluded,
not rounded. Every occurrence of a duplicated timestamp is excluded: choosing one
conflicting value would invent confidence. Missing slots remain missing. Naive or
invalid timestamps are rejected because their timezone cannot be inferred safely.

Per input, finite values within basic physical bounds count as usable; missing,
invalid and structurally excluded slots are recorded separately. These bounds are
validation bounds, not scoring thresholds. No interpolation or default substitution
is performed by the lens. Derived facts inherit the intersection of their inputs'
valid slots. A finite supplied index alone never establishes validity. Baseline
validity and PV-model input validity must be supplied or reconstructed explicitly.

An available rating needs at least 90% jointly usable slots in its evaluated
window. Unknown hours are never counted as favorable and break usable runs.
Evidence coverage describes completeness, not model accuracy or confidence in a
person's experience. Each lens withholds independently. Optional PV evidence can
be withheld independently of seasonal solar conditions and vice versa.

Saved reports remain immutable. Legacy documents without a methodology version
mean version 1; they are rendered from their saved result and rule snapshot.
New documents carry an explicit version and saved calculation/rule metadata.

## Implementation sequence

1. Implement and regression-test the evidence boundary above, without retuning.
2. Record the time-window, combination and severity contract before changing scores.
3. Implement the contract and evaluate deliberate seasonal and mixed scenarios.
4. Document calibration decisions and compare the local archive without rewriting it.

## Scoring contract

This contract was recorded before changing scoring rules and is now implemented.

Keep the existing rule/band evaluator, evidence records, saved results and six lens
identifiers. Apply the activity rules per usable hourly slot, rather than applying
daily rain totals and extrema to the whole day. The original independent-factor
deduction pattern remains: start at 100, subtract one matching band per rule, floor
at zero, then apply the smallest applicable severity ceiling.

| Lens | Local timestamp window | Required hourly inputs | Interpretation |
| --- | --- | --- | --- |
| Cycling | 08:00–20:00 | temperature, precipitation, sustained wind, gust | Outdoor riding convenience |
| Walking | 08:00–20:00 | temperature, precipitation, sustained wind, gust | Everyday walking convenience |
| Gardening | 08:00–18:00 | temperature, precipitation, sustained wind, gust | Hands-on work; not soil workability or crop need |
| Outdoor commute | 06:00–10:00 and 15:00–19:00, separately | temperature, precipitation, sustained wind, gust | Two journeys; overall score is the worse window |
| Temperature comfort | 08:00–20:00 | temperature and relative humidity | Limited temperature/humidity comfort, not thermal stress |
| Seasonal solar conditions | Full local day | radiation and a valid same-calendar reference | Radiation relative to seasonal normal; PV yield reported separately |

These fixed windows are product assumptions, not calculated daylight. Nighttime
activities are not rated. Full-day extrema remain in the evidence. Hour labels
follow the provider's timestamps; accumulated precipitation and radiation can
represent the preceding hour. Windows are approximate retrospective descriptions,
not exact departure-time recommendations.

Hourly severity ceilings have category meanings: 79 prevents “favorable”, 54
prevents “mixed”, and 29 denotes strongly constrained hours within “difficult”.
They are calibration decisions, not physiological or official warning thresholds.
Existing moderate thresholds can retain their deductions, but serious isolated
conditions can constrain an hour without needing unrelated adverse factors.

Daily/window score is the floored sum of available hourly scores divided by the
number of expected hours. This conservatively credits only known suitability: unknown
slots add no suitability credit, are labelled unknown (not bad weather), and break
favorable runs. At least 90% joint coverage is mandatory. A severe condition
(hourly ceiling at most 54) in at least 25% of expected hours limits the window
score to 54. Any strongly constrained hour (ceiling at most 29) limits the window
score to 79 and remains explicitly flagged. Thus one spike and persistent adversity
have different results; a favorable day cannot hide an extreme within its window.

Favorable is 80–100, mixed 55–79, difficult 0–54. These are heuristic suitability
categories, never percentages of safety or probabilities. Show favorable/mixed/
difficult/unknown hour counts, contiguous favorable windows, hourly evidence and
rules, category ceilings, full-day extrema, and morning/evening commute results.
Do not score daily rain accumulation again: its persistence is already represented
by wet hours. Gardening light-rain rules may differ from travel rules; neither
infers dry soil or dry roads after rain.

For solar, the primary comparison uses an uncapped ratio of daily radiation
to the valid same-calendar ERA5 mean. It does not reuse the communication index's
cloud penalty or numeric fallback. The heuristic rating and the physical ratio
will be labelled separately. PV yield is a supplemental modeled kWh/kWp value,
with separate input validity and system assumptions; it does not require a climate
baseline. Daily energy totals require all expected inputs (100% completeness),
because a partial sum is not a full-day yield. Baselines require the configured
minimum number of valid same-calendar years; missing/invalid years remain explicit.

No change will be calibrated to make the score histogram look balanced. Evaluate
ordering and explanations on a deliberately varied scenario suite and the saved
48-day sample, retaining the original files and reporting limitations.

## Implemented rule snapshot

The following table is taken from the implemented methodology snapshot. Conditions
apply to each valid evaluated hour; daily radiation uses the separate solar formula.
For each rule only its first matching band applies. Numeric lower bounds are
inclusive and upper bounds exclusive. Deductions add; ceilings use
minimum, never addition. A dash means that band imposes no extra ceiling.

| Lens | Rule / input | Condition | Deduction | Hourly ceiling |
| --- | --- | --- | ---: | ---: |
| Cycling conditions | cycling-gusts / wind_gust_max_ms | >= 18 m/s | 40 | — |
| Cycling conditions | cycling-gusts / wind_gust_max_ms | 12-18 m/s | 24 | — |
| Cycling conditions | cycling-gusts / wind_gust_max_ms | 8-12 m/s | 10 | — |
| Cycling conditions | cycling-heat / temperature_max_c | >= 35 C | 30 | — |
| Cycling conditions | cycling-heat / temperature_max_c | 30-35 C | 15 | — |
| Cycling conditions | cycling-cold / temperature_min_c | < 0 C | 25 | — |
| Cycling conditions | cycling-cold / temperature_min_c | 0-5 C | 12 | — |
| Cycling conditions | cycling-rain / precipitation_total_mm | >= 5 mm/hour | 65 | 29 |
| Cycling conditions | cycling-rain / precipitation_total_mm | 2 to < 5 mm/hour | 45 | 54 |
| Cycling conditions | cycling-rain / precipitation_total_mm | 0.5 to < 2 mm/hour | 30 | 79 |
| Cycling conditions | cycling-rain / precipitation_total_mm | 0.1 to < 0.5 mm/hour | 20 | 79 |
| Cycling conditions | cycling-sustained-wind / wind_speed_mean_ms | >= 15 m/s | 40 | 29 |
| Cycling conditions | cycling-sustained-wind / wind_speed_mean_ms | 10 to < 15 m/s | 25 | 54 |
| Cycling conditions | cycling-sustained-wind / wind_speed_mean_ms | 6 to < 10 m/s | 10 | 79 |
| Cycling conditions | severe-cold / temperature_min_c | < -15 C | 0 | 29 |
| Cycling conditions | severe-cold / temperature_min_c | -15 to < -5 C | 0 | 54 |
| Cycling conditions | severe-cold / temperature_min_c | -5 to < 0 C | 0 | 79 |
| Cycling conditions | severe-heat / temperature_max_c | >= 35 C | 0 | 29 |
| Cycling conditions | severe-heat / temperature_max_c | 30 to < 35 C | 0 | 79 |
| Cycling conditions | gust-limit / wind_gust_max_ms | >= 18 m/s | 0 | 29 |
| Cycling conditions | gust-limit / wind_gust_max_ms | 12 to < 18 m/s | 0 | 54 |
| Walking conditions | walking-gusts / wind_gust_max_ms | >= 20 m/s | 30 | — |
| Walking conditions | walking-gusts / wind_gust_max_ms | 14-20 m/s | 15 | — |
| Walking conditions | walking-heat / temperature_max_c | >= 35 C | 30 | — |
| Walking conditions | walking-heat / temperature_max_c | 31-35 C | 15 | — |
| Walking conditions | walking-cold / temperature_min_c | < -5 C | 25 | — |
| Walking conditions | walking-cold / temperature_min_c | -5 to 2 C | 10 | — |
| Walking conditions | walking-rain / precipitation_total_mm | >= 5 mm/hour | 65 | 29 |
| Walking conditions | walking-rain / precipitation_total_mm | 2 to < 5 mm/hour | 45 | 54 |
| Walking conditions | walking-rain / precipitation_total_mm | 0.5 to < 2 mm/hour | 30 | 79 |
| Walking conditions | walking-rain / precipitation_total_mm | 0.1 to < 0.5 mm/hour | 20 | 79 |
| Walking conditions | walking-sustained-wind / wind_speed_mean_ms | >= 20 m/s | 40 | 29 |
| Walking conditions | walking-sustained-wind / wind_speed_mean_ms | 15 to < 20 m/s | 25 | 54 |
| Walking conditions | walking-sustained-wind / wind_speed_mean_ms | 10 to < 15 m/s | 10 | 79 |
| Walking conditions | severe-cold / temperature_min_c | < -15 C | 0 | 29 |
| Walking conditions | severe-cold / temperature_min_c | -15 to < -5 C | 0 | 54 |
| Walking conditions | severe-cold / temperature_min_c | -5 to < 0 C | 0 | 79 |
| Walking conditions | severe-heat / temperature_max_c | >= 35 C | 0 | 29 |
| Walking conditions | severe-heat / temperature_max_c | 30 to < 35 C | 0 | 79 |
| Walking conditions | gust-limit / wind_gust_max_ms | >= 24 m/s | 0 | 29 |
| Walking conditions | gust-limit / wind_gust_max_ms | 14 to < 24 m/s | 0 | 54 |
| Outdoor commute conditions | commute-gusts / wind_gust_max_ms | >= 16 m/s | 30 | — |
| Outdoor commute conditions | commute-gusts / wind_gust_max_ms | 10-16 m/s | 14 | — |
| Outdoor commute conditions | commute-heat / temperature_max_c | >= 32 C | 20 | — |
| Outdoor commute conditions | commute-cold / temperature_min_c | < 0 C | 18 | — |
| Outdoor commute conditions | outdoor_commute-rain / precipitation_total_mm | >= 5 mm/hour | 65 | 29 |
| Outdoor commute conditions | outdoor_commute-rain / precipitation_total_mm | 2 to < 5 mm/hour | 45 | 54 |
| Outdoor commute conditions | outdoor_commute-rain / precipitation_total_mm | 0.5 to < 2 mm/hour | 30 | 79 |
| Outdoor commute conditions | outdoor_commute-rain / precipitation_total_mm | 0.1 to < 0.5 mm/hour | 20 | 79 |
| Outdoor commute conditions | outdoor_commute-sustained-wind / wind_speed_mean_ms | >= 17 m/s | 40 | 29 |
| Outdoor commute conditions | outdoor_commute-sustained-wind / wind_speed_mean_ms | 12 to < 17 m/s | 25 | 54 |
| Outdoor commute conditions | outdoor_commute-sustained-wind / wind_speed_mean_ms | 8 to < 12 m/s | 10 | 79 |
| Outdoor commute conditions | severe-cold / temperature_min_c | < -15 C | 0 | 29 |
| Outdoor commute conditions | severe-cold / temperature_min_c | -15 to < -5 C | 0 | 54 |
| Outdoor commute conditions | severe-cold / temperature_min_c | -5 to < 0 C | 0 | 79 |
| Outdoor commute conditions | severe-heat / temperature_max_c | >= 35 C | 0 | 29 |
| Outdoor commute conditions | severe-heat / temperature_max_c | 30 to < 35 C | 0 | 79 |
| Outdoor commute conditions | gust-limit / wind_gust_max_ms | >= 20 m/s | 0 | 29 |
| Outdoor commute conditions | gust-limit / wind_gust_max_ms | 14 to < 20 m/s | 0 | 54 |
| Hands-on gardening conditions | gardening-gusts / wind_gust_max_ms | >= 16 m/s | 30 | — |
| Hands-on gardening conditions | gardening-gusts / wind_gust_max_ms | 10-16 m/s | 15 | — |
| Hands-on gardening conditions | gardening-heat / temperature_max_c | >= 33 C | 25 | — |
| Hands-on gardening conditions | gardening-heat / temperature_max_c | 29-33 C | 12 | — |
| Hands-on gardening conditions | gardening-frost / temperature_min_c | < 0 C | 25 | — |
| Hands-on gardening conditions | gardening-rain / precipitation_total_mm | >= 5 mm/hour | 65 | 29 |
| Hands-on gardening conditions | gardening-rain / precipitation_total_mm | 2 to < 5 mm/hour | 45 | 54 |
| Hands-on gardening conditions | gardening-rain / precipitation_total_mm | 0.5 to < 2 mm/hour | 30 | 79 |
| Hands-on gardening conditions | gardening-rain / precipitation_total_mm | 0.1 to < 0.5 mm/hour | 10 | — |
| Hands-on gardening conditions | gardening-sustained-wind / wind_speed_mean_ms | >= 17 m/s | 40 | 29 |
| Hands-on gardening conditions | gardening-sustained-wind / wind_speed_mean_ms | 12 to < 17 m/s | 25 | 54 |
| Hands-on gardening conditions | gardening-sustained-wind / wind_speed_mean_ms | 8 to < 12 m/s | 10 | 79 |
| Hands-on gardening conditions | severe-cold / temperature_min_c | < -15 C | 0 | 29 |
| Hands-on gardening conditions | severe-cold / temperature_min_c | -15 to < -5 C | 0 | 54 |
| Hands-on gardening conditions | severe-cold / temperature_min_c | -5 to < 0 C | 0 | 79 |
| Hands-on gardening conditions | severe-heat / temperature_max_c | >= 35 C | 0 | 29 |
| Hands-on gardening conditions | severe-heat / temperature_max_c | 30 to < 35 C | 0 | 79 |
| Hands-on gardening conditions | gust-limit / wind_gust_max_ms | >= 20 m/s | 0 | 29 |
| Hands-on gardening conditions | gust-limit / wind_gust_max_ms | 14 to < 20 m/s | 0 | 54 |
| Outdoor temperature comfort | comfort-heat / temperature_max_c | >= 35 C | 45 | — |
| Outdoor temperature comfort | comfort-heat / temperature_max_c | 30-35 C | 25 | — |
| Outdoor temperature comfort | comfort-cold / temperature_min_c | < 5 C | 15 | — |
| Outdoor temperature comfort | comfort-humid-heat / hot_humid_hours | >= 28 C and >= 60% RH | 12 | — |
| Outdoor temperature comfort | severe-cold / temperature_min_c | < -15 C | 0 | 29 |
| Outdoor temperature comfort | severe-cold / temperature_min_c | -15 to < -5 C | 0 | 54 |
| Outdoor temperature comfort | severe-cold / temperature_min_c | -5 to < 0 C | 0 | 79 |
| Outdoor temperature comfort | severe-heat / temperature_max_c | >= 35 C | 0 | 29 |
| Outdoor temperature comfort | severe-heat / temperature_max_c | 30 to < 35 C | 0 | 79 |
| Outdoor temperature comfort | humid-heat-limit / humid_heat_temperature_c | >= 32 C and >= 60% RH | 0 | 54 |
| Outdoor temperature comfort | humid-heat-limit / humid_heat_temperature_c | 28 to < 32 C and >= 60% RH | 0 | 79 |

## Saved evidence and source vocabulary

`source` identifies provider, product, hourly resolution and whether this is gridded
historical weather or synthetic demo data. `input_quality` lists missing/invalid
slots per input; `evidence_quality` lists structural gaps, duplicates and off-grid
rows. `hourly_evidence` saves usable source values, with invalid values represented
as null. Fact `sources` identifies dependencies; `kind` distinguishes derived,
fallback and unverified results, and `reason` explains an evidence gap.

The live baseline snapshot stores the same-calendar ERA5 daily sample for each
standard-period year, its validity status, valid/expected counts, and the configured
minimum (normally 24 of 30 years). Valid zero-radiation days remain zero; missing
values do not become zero. February 29 uses February 28 in non-leap reference years.
The mean is recomputed from valid samples before scoring. A zero/nonfinite reference,
wrong reference date, duplicate sample dates or insufficient valid years withholds
the seasonal comparison. Missing reference years affect baseline adequacy, not the
hourly weather coverage percentage.

The PV snapshot includes model identity, tilt, azimuth and temperature coefficient.
It requires every hourly radiation component, temperature and 10 m wind input, plus
an explicit upstream derived-status marker. The existing energy calculators may
retain numerical fallbacks for other outputs; their fallback metadata is not a
license to rate the activity lens. The deprecated `energy` argument is not used
as evidence for the v2 seasonal comparison.

Each activity saves its relevant-period aggregates, per-hour results, triggered
rules, limiting-factor duration/value range, favorable runs and daily context.
The commute saves both journeys, even when one is withheld; its overall score is
withheld if either journey lacks sufficient evidence. A new daily summary references
the methodology version as well as the evidence filename. All rendering uses saved
scores and rules, not a recalculation from current code.

## Verification and interpretation

See the [calibration review](activity_lenses_calibration.md) for the 26 deliberate
scenarios and the read-only comparison of the 48 historical days. These are checks
of consistency, ordering, explanation quality and sample behavior, not empirical
proof of universal thresholds. No machine learning, personal tolerance model,
medical index, new provider, or historical migration is introduced.
