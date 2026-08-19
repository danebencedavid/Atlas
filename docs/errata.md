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

- Observational completeness is now gated per input, with per-day coverage, so a
  thin trailing day cannot hide inside an average. Radar is judged against what
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
