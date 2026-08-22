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

### Original audit record (superseded by the closure below)

Found while auditing on 2026-08-22. The numbered findings are preserved here as
the contemporaneous audit record; their current status is stated below.

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
4. **A total station failure publishes; a two-hour staleness does not.** The
   freshness assertion in `cli.py` is guarded by `if not station.frame.empty:`.
5. **The coverage gates are advisory.** `cli.py` turns `not coverage.ok` into a
   quality note. Only the freshness assertion refuses to publish.
6. **`demo.py` is 768 lines of untested parallel pipeline.** No test imports it.
   It duplicates the shape of `run_pipeline`, which is the code path that shipped
   a `NameError` through a green suite in `8571ddc`.
7. **Attribution for HungaroMet, Energy-Charts and Copernicus is still absent
   from the site.** Only Open-Meteo is credited. HungaroMet consent for modified
   use of Open Data Portal data is requested and unanswered.

### Publication-integrity follow-up, completed 2026-08-22

The engineering defects above were closed without changing the scientific scope:

1. **Per-day station coverage is now enforced.** Every local day must meet the
   configured station threshold as well as the aggregate window. Thin days are
   always named in the coverage notes, including when the aggregate would pass.
2. **The withheld-build record now fails closed.** Invalid JSON, an unreadable
   file, a missing top-level key, or a schema-invalid entry raises
   `WithheldStatusError` and blocks publication. The pipeline reads the record
   before fetching or rendering anything.
3. **Affected daily editions now carry the measured erratum.** Daily artefacts
   intentionally contain no copied observation ledger, so the archive builder
   measures the corresponding saved 72-hour period and propagates that exact,
   reproducible banner to the published daily copy.
4. **A total station failure is refused.** Missing station data is passed into
   the same freshness assertion as a stale series instead of skipping it.
5. **Station coverage is a hard publication gate.** It supports headline values
   and the objective event record. Radar and lightning remain optional by
   design: when unavailable they are identified as unavailable and never
   converted into zero observations.
6. **Source attribution is now visible on every generated page and figure.** It
   credits HungaroMet, Energy-Charts/Fraunhofer ISE, Open-Meteo and Copernicus,
   including the modified-Copernicus notice and disclaimer.

Two limits remain explicit:

- `demo.py` remains a parallel synthetic-layout pipeline. It is not called by
  the scheduled production workflow, so it is outside this publication gate,
  but its duplication is still a maintenance defect.
- HungaroMet's current English Open Data Portal terms say modified use requires
  prior written consent. Attribution is now complete, but the requested consent
  remains unanswered. That external permission risk cannot be represented as a
  completed engineering fix.
