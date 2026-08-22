# Errata

Corrections to published Atlas editions. Editions are annotated, never
regenerated: rewriting one would destroy the record of what was actually
published on the day.

## 2026-08-19 — incomplete station observations in six editions

### What was wrong

Six saved 72-hour editions were built from a station record that stopped short of
their own reporting window. Two full days were observed and the final day — the
day each edition headlines — was almost entirely unobserved.

| edition | window coverage | final day |
|---|---|---|
| 2026-07-30_2026-08-01 | 156/432 (36%) | 0/144 (0%) |
| 2026-08-02_2026-08-04 | 300/432 (69%) | 12/144 (8%) |
| 2026-08-05_2026-08-07 | 300/432 (69%) | 12/144 (8%) |
| 2026-08-08_2026-08-10 | 300/432 (69%) | 12/144 (8%) |
| 2026-08-11_2026-08-13 | 300/432 (69%) | 12/144 (8%) |
| 2026-08-14_2026-08-16 | 300/432 (69%) | 12/144 (8%) |

Figures are recomputed from each edition's own committed observation file by
`python -m atlas.errata`, so every number above is reproducible from the edition
it describes.

### Why it happened

The HungaroMet 10-minute export regenerates once daily at about 09:50 UTC, and
the file published then covers through 23:50 UTC the previous day. The build ran
at 05:15 UTC, nearly five hours earlier, so it read the *previous* day's file and
always missed the last 22 hours of its own window.

Nothing caught it because the completeness gate validated only the gridded hourly
frame. That frame was complete, so every affected edition carries the note *"Data
completeness check passed with 72/72 expected local-period hours"* while its
station record sat at 69%. The station, radar and lightning inputs had no
threshold at all.

### What is affected

Quantities derived from the station record across the window:

- objective frontal passage detection, which reads the station series directly,
  and therefore could not see the final day of any affected edition
- the objective phenomena ledger, which draws on station, radar and lightning
- the period mean temperature, precipitation total and maximum gust in the
  station observation ledger

Gridded quantities are **not** affected. The hourly analysis was complete in every
case, so anomalies, climate context, energy yields and the almanac stand.

### The fix

- Observational completeness is now gated per input, and per-day coverage is
  computed and published. ~~A thin trailing day cannot hide inside an average.~~
  **Corrected 2026-08-22: that claim was wrong. The gate is enforced on the
  aggregate only; the per-day figures are reported, never enforced. See the
  2026-08-22 entry below.** Radar is judged against what
  the provider still retains, since its archive keeps about 71 hours against a
  72-hour window and gating on the window would fail permanently on a known
  structural limit.
- The build asserts observation freshness directly: it compares the newest
  observation retrieved against the window end and refuses to publish if it falls
  short. This, not the schedule, is the guarantee.
- The schedule moved from 05:15 to 11:00 UTC. That is an optimisation which makes
  the assertion likely to pass on the first attempt; the provider controls its own
  regeneration time and can change it without notice.
- Per-day station and radar coverage is published on the Methods and Evidence
  page, with the radar retention limit stated so its leading-edge gap reads as
  structural rather than as an outage.

### Also corrected at the same time

A failed lightning archive and a genuinely quiet period both produced an empty
frame, so an edition could print "0 lightning event(s)" for an archive that never
answered — stating an observation nobody made, with the reassuring reading as the
default. Lightning now carries an explicit availability state and the published
text distinguishes the two.


## 2026-08-22 — corrections to the entry above, and defects recorded but not fixed

### The per-day gating claim in the entry above was false

The 2026-08-19 entry stated that observational completeness is gated per input
"with per-day coverage, so a thin trailing day cannot hide inside an average".
It is not. `validate_station_period` in `src/atlas/quality.py` computes the
per-day frame, then sets `ok` from the whole-window aggregate alone:

```python
coverage = observed / expected
...
ok=available and coverage >= minimum_coverage
```

The per-day breakdown is emitted only inside the `elif coverage < minimum_coverage`
branch, so it appears only once the aggregate has already failed. Demonstrated on
a three-day window with 21 ten-minute records removed from the final day and
nowhere else:

| aggregate | gate | final day | notes emitted |
|---|---|---|---|
| 95.14% | **passes** | 85.4% | **none** |

A day at 85% coverage passes the gate silently. The claim was carried into this
document from the commit message of `07aa5f1`, which said the same thing:
"Each observational input now carries a coverage figure and a threshold, with
per-day breakdowns so a thin trailing day cannot hide inside an average." That
commit message overstated what was implemented. Both are corrected here; the
commit itself cannot be, so this note is the record.

What the 2026-08-19 entry got right is the more important half: the freshness
assertion, not the gate, is the load-bearing guarantee. A *trailing* gap larger
than two hours is still refused. What passes is a gap in the middle of the final
day, which the aggregate absorbs and which `max(time)` cannot see.

An erratum containing an uncorrected error is the one thing this mechanism must
not ship.

### Corrected the same day: CAMS irradiance truth was one hour out of step

`parse_cams_csv` read the **start** of the CAMS observation interval as the valid
time. CAMS integrates over `[start, end)` and labels the row by its start;
Open-Meteo labels hourly radiation by the end of the hour it averages over, as
the preceding-hour mean. Every irradiance pair was therefore one hour out of step.

Measured on the full backfill at 24 h lead, shortwave radiation:

| truth | as published | correctly aligned |
|---|---|---|
| CAMS / ecmwf_ifs025 | 55.23 | **32.25** |
| CAMS / icon_seamless | 54.57 | **32.35** |
| ERA5 / ecmwf_ifs025 | **19.44** | 52.40 |

ERA5, which is also Open-Meteo, is correct at zero shift; only CAMS needed the
hour. Two consequences:

- Every CAMS figure in `docs/forecast_verification.md` is inflated. The reported
  jump in irradiance error on moving from ERA5 to CAMS is roughly half real:
  +66% for shortwave at 24 h, not +184%.
- A uniform time shift is exactly the kind of structure a correction learns and
  removes. Fitting the Stage 2 model against the misaligned truth returned a
  45.3% improvement in shortwave MAE; against the corrected truth the same
  method returns 9.4%. Around four-fifths of that headline would have been the
  model undoing a parser bug and reporting it as skill.

Nothing in a seasonal, diurnal or sky-regime average reveals a uniform shift, so
the convention is now pinned by a two-row test in `tests/test_cams.py` rather
than left to be caught downstream.

### Recorded, open, not fixed

Found while auditing on 2026-08-22 and deliberately left alone, so that a single
day's work could reach a Stage 2 number instead of a longer list of corrections.

1. **The per-day gate is not enforced** (above). `quality.py`. Open.
2. **`record_withheld` reports "nothing withheld" when its own record is
   unreadable.** `build_status.py` catches `JSONDecodeError` and `OSError` and
   returns `[]`. The mechanism whose entire purpose is to stop a silent absence
   goes silent in exactly the case it exists for, and
   `test_build_status.py::test_a_corrupt_record_does_not_break_the_build` asserts
   this as correct. Separately, `WithheldBuild(**entry)` sits outside the `try`,
   so a schema change raises `TypeError` and breaks the build instead.
3. **No daily edition carries an erratum.** 96 pages under `reports/periods/`
   are annotated; 0 of 180 files under `reports/daily/` are. `measure_edition`
   splits the directory name on `_` and daily directories are named `2026-08-14`,
   and daily editions ship no `data/` directory, so coverage cannot be recomputed
   from them even in principle. The daily edition is the more public product and
   it still prints station-derived headline figures — "Airport mean 20.3 C,
   Airport precipitation 0.0 mm, Peak airport gust 8.4 m/s" for 2026-08-14 —
   for days the station barely observed.
4. **The verification report contradicts itself on its own coverage.**
   `forecast_cli.py` computes `ERA5-fallback pairs` as every pair that is not
   station-truth, which counts the 599,159 CAMS pairs as ERA5 fallback. The
   published report therefore states "ERA5-fallback pairs: 801,111" (52%) and
   "201,952 of 1,540,281 pairs (13.1%) fall back to ERA5" fifteen lines apart.
   13.1% is the true figure.
5. **`docs/forecast_verification.md` is stale.** Generated 2026-08-19 19:02 UTC,
   before the CAMS alignment fix, before `best_match` was excluded, and before
   the live collector wrote anything. Every irradiance number in it is wrong and
   every `best_match` row in it is uninterpretable.
6. **The CAMS `Reliability` column is ignored.** `parse_cams_csv` reads GHI, BHI
   and DHI only. Retrievals with reliability as low as 0.72 carry the same weight
   as reliability 1.0.
7. **A total station failure publishes; a two-hour staleness does not.** The
   freshness assertion in `cli.py` is guarded by `if not station.frame.empty:`.
8. **The coverage gates are advisory.** `cli.py` turns `not coverage.ok` into a
   quality note. Only the freshness assertion refuses to publish.
9. **The live and backfill collectors carry different lead structures.** Backfill
   lands on 24/48/72 h exactly; the live collector derives lead from issue time
   and spans 0-96 h. `verify` now defaults to `--kind backfill` so the two cannot
   be scored together by accident, but nothing reconciles them.
10. **`demo.py` is 768 lines of untested parallel pipeline.** No test imports it.
    It duplicates the shape of `run_pipeline`, which is the code path that shipped
    a `NameError` through a green suite in `8571ddc`.
11. **Attribution for HungaroMet, Energy-Charts and Copernicus is still absent
    from the site.** Only Open-Meteo is credited. HungaroMet consent for modified
    use of Open Data Portal data is requested and unanswered.

### The NOAA ISD fallback, if HungaroMet consent is refused

Established 2026-08-22, not built. Station truth underpins the wind and
temperature results, so the question is whether a redistributable substitute
exists at this point.

**It does, and it is the same physical site.** NOAA Integrated Surface Database
carries USAF `128820` / WBAN `99999`, ICAO **LHDC**, "DEBRECEN", 47.489 N
21.615 E, 110 m, with a record beginning 1931-01-04. That is Debrecen Airport,
the same location as HungaroMet station 64711. The feed is METAR and SYNOP
distributed under WMO Resolution 40 as essential data, so redistribution is not
in question.

Coverage measured over 2024-01-01 to 2025-08-24, 30,043 records:

| quantity | of records | of hours in span |
|---|---|---|
| temperature | 98.6% | **95.9%** |
| dewpoint (gives RH with temperature) | 98.3% | **95.7%** |
| wind speed | 100% | **96.5%** |
| wind direction | 80.8% | — |

27,597 records are FM-15 (METAR), 2,446 FM-12 (SYNOP); two to three
observations per hour is typical. 587 hours are missing, concentrated in two
multi-day outages (2024-03: 111 h, 2024-11: 101 h) with the rest scattered.

**Three limits, and the first is decisive.**

1. **The archive is about a year behind.** `global-hourly/access/2026/` returns
   404; there is no 2026 directory at all, and the maximum `END` across every
   station worldwide in `isd-history.csv` is 2025-08-28. ISD therefore covers
   2024-01-22 to 2025-08-24 of the 2024-01-22 to 2026-08-18 pairing span, about
   62% of it. **The current holdout, 2026-02-19 to 2026-08-18, lies entirely
   outside ISD coverage.** If consent is refused, today's number cannot be
   reproduced from ISD; the holdout would have to move back roughly a year, and
   ongoing verification could not run at all.
2. **No gusts.** The `OC1` gust group is present on 4.3% of records.
   `wind_gusts_10m` cannot be verified against ISD.
3. **A different quantity.** METAR is a spot reading at :00 and :30, not a
   ten-minute record. Switching truth mid-study moves the yardstick, so any
   comparison across the switch would have to be made against both.
