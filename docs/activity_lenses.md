# Atlas activity lenses

Activity lenses translate a completed Debrecen weather day into a small set of
repeatable, evidence-backed convenience ratings. They do not forecast conditions
or replace official warnings, health guidance, or personal judgement.

## Contract

The engine emits `atlas.activity-lenses/1`. Each document records:

- the completed local calendar date and timezone;
- expected and observed hourly coverage, including 23- and 25-hour DST days;
- the two local commute windows used by the commute lens;
- one result per lens, with its status, rating, score and evidence;
- every triggered rule, threshold, severity, explanation and score deduction;
- the source column or derived daily evidence behind every displayed fact.
- the full calculation method: starting score, rating bands, coverage policy and
  every possible penalty threshold for every lens.

A lens is `insufficient-evidence` when any required fact has less than 90% hourly
coverage. Other lenses remain available when their own inputs are complete. A
missing normalized solar index is never inferred from raw radiation alone.

## Initial lenses

The first contract defines six observational lenses:

1. cycling conditions;
2. walking conditions;
3. outdoor commute conditions for 06:00-10:00 and 15:00-19:00 local time;
4. hands-on gardening conditions;
5. solar-energy conditions;
6. outdoor temperature comfort.

Scores begin at 100 and only transparent, declared rules can reduce them. A score
of 80-100 is `favorable`, 55-79 is `mixed`, and 0-54 is `difficult`. These labels
describe the product heuristics, not safety categories. Rain accumulation and
duration, gusts, temperature, paired warm/humid hours and the normalized Atlas
solar index are evaluated independently so the reason for a rating remains
inspectable.

## Delivery phases

- Phase 1 provides the deterministic engine, schema and tests without changing
  any public page. Complete.
- Phase 2 writes the result atomically to `data/activity_lenses.json`, references
  it from the daily evidence summary, and includes it before a new edition is
  frozen. Complete for live and demo builds.
- Phase 3 renders the exact saved results on the daily overview, including each
  score, rating, limiting evidence, calculation method, disclaimer and JSON
  download. A lens symbol, section frame and accessible rating-colored accents
  distinguish the block while retaining Atlas's existing visual components.
  Complete.

The engine intentionally reads source evidence rather than archived HTML. Legacy
editions without the required evidence remain unchanged and do not receive
retrospectively invented ratings.
