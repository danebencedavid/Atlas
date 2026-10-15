# Activity Lenses v2: calibration review

Reviewed against the local implementation on 2026-10-15. This is a deterministic scenario and archive review, not a clinical, safety, or user-preference validation. No thresholds were fitted to a desired score distribution.

## Representative scenario evaluation

All 26 scenarios use complete hourly evidence and an explicitly synthetic seasonal reference. Solar is held at 92% of normal to isolate activity behavior; solar validity and comparison semantics have separate regression tests. Scores below are the resulting v2 values, not forecasts.

| Scenario | Cycling | Walking | Commute | Gardening | Temperature comfort |
| --- | ---: | ---: | ---: | ---: | ---: |
| mild dry | 100 | 100 | 100 | 100 | 100 |
| mild winter | 100 | 100 | 100 | 100 | 100 |
| freezing | 75 | 79 | 79 | 75 | 79 |
| severe cold | 29 | 29 | 29 | 29 | 29 |
| cold windy | 10 | 50 | 27 | 20 | 54 |
| cold calm dry | 54 | 54 | 54 | 54 | 54 |
| comfortable warm | 100 | 100 | 100 | 100 | 100 |
| hot | 79 | 79 | 79 | 79 | 75 |
| severe heat | 29 | 29 | 29 | 29 | 29 |
| hot humid | 79 | 79 | 79 | 79 | 54 |
| hot dry | 29 | 29 | 29 | 29 | 29 |
| breezy | 90 | 100 | 100 | 100 | 100 |
| persistent strong wind | 29 | 54 | 45 | 45 | 100 |
| extreme gusts | 29 | 29 | 29 | 29 | 100 |
| overnight cold | 100 | 100 | 54 | 100 | 100 |
| warm morning hot afternoon | 54 | 54 | 29 | 54 | 54 |
| overnight rain | 100 | 100 | 100 | 100 | 100 |
| brief shower | 97 | 97 | 100 | 97 | 100 |
| persistent light rain | 79 | 79 | 79 | 90 | 100 |
| heavy rain | 29 | 29 | 29 | 29 | 100 |
| dry middle window | 54 | 54 | 54 | 54 | 100 |
| one gust spike | 79 | 96 | 100 | 79 | 100 |
| repeated gusts | 54 | 54 | 54 | 54 | 100 |
| cold wet windy | 11 | 45 | 28 | 20 | 79 |
| wet morning dry evening | 79 | 79 | 29 | 79 | 100 |
| dry morning wet evening | 54 | 54 | 29 | 54 | 100 |

The scenario definitions are executable in [test_activity_lens_calibration.py](../tests/test_activity_lens_calibration.py). They explicitly assert ordering, severe-condition categories, matched explanations, hour counts, favorable runs and morning/evening asymmetry.

Review observations:

- Severe cold (−20°C), severe heat (40°C), and hot dry conditions (36°C) constrain every temperature-dependent activity to difficult without requiring rain or wind.
- A 22 m/s cycling gust in one daytime hour limits the day to mixed (79); four such hours produce difficult (54). All-day extreme gusts produce 29. The time information is retained rather than replacing the whole day with its maximum.
- A one-hour 1 mm shower leaves 11 favorable cycling hours and a score of 97. Continuous light rain produces 79; heavy hourly rain produces 29. The gardening light-rain score is 90, an explicit activity-specific tolerance rather than a soil-workability claim.
- Overnight cold and rain do not penalize the stated daytime activity windows. Cold during the morning commute still affects that journey. Overnight rainfall remains in full-day context; dry weather does not prove dry roads or workable soil.
- A dry four-hour middle-of-day window remains visible on a day that rates difficult overall. A warm morning/very hot afternoon produces distinct commute outcomes and a difficult overall commute.
- Comfort stays 100 during wind/rain-only scenarios because it is deliberately temperature/humidity comfort, not overall outdoor suitability. The label and methodology state this limitation.

## Review of the 48 saved days

The local sample spans **2026-08-27 to 2026-10-13**. Original JSON files were SHA-256 checked before and after the comparison; all 48 stayed unchanged. New results were evaluated in memory using saved hourly weather and existing cached ERA5 daily references. No production data was refreshed.

| Lens | Original days scoring 100 | V2 days scoring 100 |
| --- | ---: | ---: |
| cycling | 16 | 20 |
| walking | 30 | 32 |
| outdoor commute | 33 | 31 |
| gardening | 23 | 28 |
| solar energy | 45 | 43 |
| outdoor comfort | 45 | 45 |

The uncapped seasonal radiation ratio ranged from **44.511% to 155.813%**; **43 of 48 days exceeded 100%**. Thus much of the solar ceiling concentration reflects genuinely above-normal radiation within this comparison. V2 retains the actual ratio, even when the convenience score reaches 100. Removing the inherited cloud penalty and categorical step mapping gives scores of 44, 56, 58, 82 and 98 on the five below-normal days; the other 43 remain 100.

The temperature-comfort sample had relevant-window minima no lower than **6.2°C**, maxima no higher than **33.9°C**, and only three days crossing its active warm thresholds. V2 still gives 100 on 45 days. The three affected dates change from 75 to **91 (August 30), 83 (August 31), and 87 (September 9)** because warm conditions did not occupy every evaluated hour. This supports both explanations: the sample is mild for this limited model, and coarse bands have deliberate plateaus. It does not establish universal calibration quality.

Walking and gardening become more favorable in this sample because overnight accumulation and isolated maxima no longer penalize every activity hour. This was reviewed as an intended semantic change, not optimized away to keep the old histogram. Severe and persistent adverse conditions remain constrained in the independent scenario suite.

## Calibration decisions and limitations

The 79 and 54 caps are the upper bounds of mixed and difficult, so they have explicit category meanings. The 29 ceiling reserves a visibly lower part of difficult for strongly constrained hours. The 25% persistence criterion means three of twelve daytime hours, or one of four commute hours. All are provisional product choices, not official warning thresholds.

Retained moderate temperature/gust deductions provide continuity with v1. New hourly precipitation bands prevent double-counting daily accumulation and wet duration; new sustained-wind rules distinguish persistent wind from gust peaks. Temperature comfort intentionally omits physiological claims, wind chill, radiant temperature, clothing and exertion. A comfortable-temperature score can coexist with a difficult cycling score.

Fixed local windows are not actual daylight and do not cover night activities. Hourly products cannot resolve sub-hour gust duration or the exact time of a shower. Timestamp-labelled precipitation may summarize the preceding hour. Gardening does not infer soil drainage; traveling lenses do not infer ice, road condition, lightning exposure or route shelter. Missing or invalid evidence is withheld rather than compensated by a plausible fallback.

Future threshold revisions should test this scenario suite and new representative evidence, record why a boundary changes, and use a new methodology version. Neither this short archive nor the synthetic suite constitutes a full-year field validation.

## Reproducing the review

Run from the repository environment:

```text
python -m pytest tests/test_activity_lenses.py tests/test_activity_lens_calibration.py tests/test_energy.py tests/test_climatology.py tests/test_report.py -q
python tests/test_activity_lens_calibration.py
python tests/test_activity_lens_calibration.py --archive
```

The archive comparison requires the saved daily CSV/JSON files and the configured standard-period climate caches; it never fetches or rewrites them. The scenario and invariant tests do not require those caches. See [methodology 2](activity_lenses_v2.md) for the contract and exact rules.

## Final integration verification

The complete repository suite passed **179 tests**. Two existing `nbformat` /
`jsonschema` deprecation warnings remain. Tests include legacy rendering without
recalculation, deterministic serialization, both DST transitions, leap-day
references, fallback rejection, missing/joint coverage and monotonic severity
boundaries. All 89 documented rule bands were checked against the implementation.

An isolated synthetic build produced a v2 daily report with distinct morning and
evening journeys, independent PV reporting and the saved methodology identifier.
Its daily bundle passed integrity validation at **252,874 / 262,144 bytes**; its
published edition measured **415,852 / 1,048,576 bytes**. This deliberately larger
budget fixture includes three-day weather and station tables, not just daily ones.
No archive size limits were increased.

Production inputs, workflows and saved historical reports have no tracked changes.
No deployment or full-year production refresh was performed. This verification
checks generated report content and bundle integrity; it does not claim a browser
visual audit or full-year field validation.
