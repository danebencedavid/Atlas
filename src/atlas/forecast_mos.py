"""Stage 2: fit a model output statistics correction and measure its skill.

The question is narrow on purpose. One model, one lead time, one holdout, three
variables, and every design choice made so the number can be believed rather than
so it can be large.

**Residual target.** The model predicts ``observed - forecast``, not ``observed``.
Predicting the observation lets a learner reproduce the diurnal cycle and score
well while adding nothing to the forecast. Predicting the residual makes the
forecast the starting point, so any skill reported is skill the forecast did not
already have.

**Issue-time features only.** Every feature is derivable at the moment the
forecast is issued: the forecast value itself, the disagreement between the two
models, and harmonics of hour and day-of-year. Nothing reads an observation, and
nothing reads a recent error. That is what removes the need for a purge gap:
with no lagged-error feature there is no window in which training and evaluation
can share an observation.

**One untouched holdout.** Split on valid time, never at random. Everything from
``HOLDOUT_START`` forward is scored once, at the end. Hourly weather is strongly
autocorrelated, so a random split puts the hour before and the hour after the
same event on opposite sides of the divide and reports a number that cannot be
earned in operation.

**Two baselines.** Raw NWP says whether the correction helped. Training-period
climatology says whether the forecast is worth having at all. A correction that
beats raw NWP but loses to climatology has not been shown to be useful.

Stage 1's report, ``docs/forecast_verification.md``, is stale: its irradiance
figures predate the CAMS alignment fix and its tables still carry ``best_match``.
Every baseline here is recomputed from the same pairs rather than quoted from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

REPORT_PATH = Path("docs/forecast_mos.md")

# Everything from here forward is scored once and never trained on.
HOLDOUT_START = pd.Timestamp("2026-02-19", tz="UTC")

TARGET_MODEL = "icon_seamless"
SPREAD_MODEL = "ecmwf_ifs025"
LEAD_HOURS = 24

SEASONS = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
           6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}

# Wind first: it carries a standing negative bias at every hour and in every
# season, which is the cleanest thing a correction can remove. Irradiance last:
# it depends on a satellite retrieval with a timestamp convention, a snow caveat,
# and a reliability column this pipeline still ignores.
VARIABLES: list[tuple[str, str, str]] = [
    ("wind_speed_10m", "station", "m/s"),
    ("temperature_2m", "station", "degC"),
    ("shortwave_radiation", "cams", "W/m2"),
]

FEATURES = ["forecast", "spread", "hour_sin", "hour_cos", "doy_sin", "doy_cos"]

# Above this, an irradiance result is a bug hunt before it is a result. Against
# the misaligned CAMS truth this same method returned 45.3%, nearly all of which
# was the model undoing a one-hour parser error and reporting it as skill.
IRRADIANCE_SUSPICION_THRESHOLD = 15.0

# Below these the split is not worth scoring.
MINIMUM_TRAIN_ROWS = 1000
MINIMUM_HOLDOUT_ROWS = 200


@dataclass(frozen=True)
class MosResult:
    variable: str
    truth_source: str
    unit: str
    n_train: int
    n_holdout: int
    holdout_start: pd.Timestamp
    holdout_end: pd.Timestamp
    raw_mae: float
    climatology_mae: float
    mos_mae: float
    raw_bias: float
    mos_bias: float
    seasonal: pd.DataFrame

    @property
    def skill_pct(self) -> float:
        """Change in MAE against raw NWP. Negative is an improvement."""
        return (self.mos_mae / self.raw_mae - 1.0) * 100.0

    @property
    def beats_climatology(self) -> bool:
        return self.mos_mae < self.climatology_mae

    @property
    def suspicious(self) -> bool:
        """True when an irradiance result is large enough to be a defect first."""
        return (
            self.variable == "shortwave_radiation"
            and -self.skill_pct > IRRADIANCE_SUSPICION_THRESHOLD
        )


def build_design(
    forecasts: pd.DataFrame,
    truth: pd.DataFrame,
    variable: str,
    truth_source: str,
) -> pd.DataFrame:
    """One row per valid hour: the forecast, the spread, the calendar, the truth."""
    subset = forecasts[
        (forecasts["variable"] == variable) & (forecasts["lead_time_hours"] == LEAD_HOURS)
    ]
    if subset.empty:
        return pd.DataFrame()
    wide = subset.pivot_table(index="valid_time_utc", columns="model", values="value")
    if TARGET_MODEL not in wide:
        return pd.DataFrame()
    wide = wide.dropna(subset=[TARGET_MODEL]).reset_index()

    # The truth source is named rather than inferred. Falling back to whatever the
    # truth table happens to hold would quietly score irradiance against ERA5.
    observed = truth[
        (truth["variable"] == variable) & (truth["truth_source"] == truth_source)
    ]
    frame = (
        wide.merge(observed[["valid_time_utc", "observed"]], on="valid_time_utc", how="inner")
        .sort_values("valid_time_utc")
        .reset_index(drop=True)
    )
    if frame.empty:
        return frame

    hour = frame["valid_time_utc"].dt.hour
    day = frame["valid_time_utc"].dt.dayofyear
    frame["forecast"] = frame[TARGET_MODEL]
    # Disagreement between the two models proxies how uncertain the atmosphere
    # was, and it is known at issue time.
    frame["spread"] = (
        (frame[TARGET_MODEL] - frame[SPREAD_MODEL]).abs() if SPREAD_MODEL in frame else np.nan
    )
    frame["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    frame["doy_sin"] = np.sin(2 * np.pi * day / 365.25)
    frame["doy_cos"] = np.cos(2 * np.pi * day / 365.25)
    frame["residual"] = frame["observed"] - frame["forecast"]
    frame["hour"] = hour
    frame["month"] = frame["valid_time_utc"].dt.month
    frame["season"] = frame["month"].map(SEASONS)
    return frame


def fit_and_score(
    frame: pd.DataFrame, variable: str, truth_source: str, unit: str
) -> MosResult | None:
    """Train strictly before the holdout, predict across it, score once."""
    train = frame[frame["valid_time_utc"] < HOLDOUT_START]
    holdout = frame[frame["valid_time_utc"] >= HOLDOUT_START]
    if len(train) < MINIMUM_TRAIN_ROWS or len(holdout) < MINIMUM_HOLDOUT_ROWS:
        return None

    # Library defaults throughout. Nothing here is tuned, so nothing here can have
    # been tuned against the holdout.
    model = HistGradientBoostingRegressor(random_state=0)
    model.fit(train[FEATURES], train["residual"])
    corrected = holdout["forecast"] + model.predict(holdout[FEATURES])

    # Climatology is the mean observation for that month and hour, taken from the
    # training period only, so it never sees the holdout either.
    climatology = train.groupby(["month", "hour"])["observed"].mean()
    keys = pd.MultiIndex.from_arrays([holdout["month"], holdout["hour"]])
    climatology_pred = climatology.reindex(keys).to_numpy()

    raw_error = (holdout["forecast"] - holdout["observed"]).to_numpy()
    mos_error = (corrected - holdout["observed"]).to_numpy()
    seasonal = (
        pd.DataFrame(
            {
                "season": holdout["season"].to_numpy(),
                "raw": np.abs(raw_error),
                "mos": np.abs(mos_error),
            }
        )
        .groupby("season", observed=True)
        .agg(n=("raw", "size"), raw_mae=("raw", "mean"), mos_mae=("mos", "mean"))
        .reset_index()
    )
    seasonal["skill_pct"] = (seasonal["mos_mae"] / seasonal["raw_mae"] - 1.0) * 100.0

    return MosResult(
        variable=variable,
        truth_source=truth_source,
        unit=unit,
        n_train=len(train),
        n_holdout=len(holdout),
        holdout_start=holdout["valid_time_utc"].min(),
        holdout_end=holdout["valid_time_utc"].max(),
        raw_mae=float(np.abs(raw_error).mean()),
        climatology_mae=float(
            np.nanmean(np.abs(climatology_pred - holdout["observed"].to_numpy()))
        ),
        mos_mae=float(np.abs(mos_error).mean()),
        raw_bias=float(raw_error.mean()),
        mos_bias=float(mos_error.mean()),
        seasonal=seasonal,
    )


def run_mos(forecasts: pd.DataFrame, truth: pd.DataFrame) -> list[MosResult]:
    """Fit and score every configured variable, in the configured order."""
    results: list[MosResult] = []
    for variable, truth_source, unit in VARIABLES:
        frame = build_design(forecasts, truth, variable, truth_source)
        if frame.empty:
            continue
        result = fit_and_score(frame, variable, truth_source, unit)
        if result is not None:
            results.append(result)
    return results


def _preamble(results: list[MosResult], generated: str) -> list[str]:
    """Everything a reader needs before the first number, stated on its face."""
    holdout = results[0] if results else None
    span = (
        f"{holdout.holdout_start} to {holdout.holdout_end}"
        if holdout is not None
        else "no holdout was scored"
    )
    return [
        "# Stage 2: MOS skill against raw NWP at Debrecen",
        "",
        f"Generated by `atlas-forecast mos` on {generated}.",
        "",
        "## What this measures, before any number",
        "",
        f"- **Holdout:** {span}. Split on valid time, never at random. Scored once.",
        f"- **Training:** everything strictly before {HOLDOUT_START.date()}.",
        f"- **Model:** `{TARGET_MODEL}` at {LEAD_HOURS} h lead only.",
        "- **Target:** the residual, `observed - forecast`, not the observation.",
        f"- **Features, all knowable at issue time:** {', '.join(f'`{name}`' for name in FEATURES)}. "
        f"`spread` is `|{TARGET_MODEL} - {SPREAD_MODEL}|`. No feature reads an observation "
        "and none reads a recent error, so no purge gap is required.",
        "- **Learner:** `sklearn.ensemble.HistGradientBoostingRegressor` at library "
        "defaults, `random_state=0`. Nothing is tuned, so nothing is tuned against the holdout.",
        "- **Baselines:** raw NWP, and a training-period climatology of mean observation "
        "by month and hour.",
        "- **Truth:** HungaroMet station 64711 for wind and temperature; CAMS "
        "satellite-derived irradiance for shortwave radiation. CAMS is not a ground "
        "measurement.",
        "",
        "> `docs/forecast_verification.md` is **stale**. It was generated before the CAMS "
        "interval-labelling fix and still carries `best_match` rows. Every baseline below "
        "is recomputed from the same pairs rather than quoted from it.",
        "",
        "## What this does not cover",
        "",
        "- One model and one lead time. Nothing here says how `ecmwf_ifs025` behaves, or "
        "how skill decays to 48 and 72 h.",
        "- One holdout, spanning late winter through summer. There is no autumn in it and "
        "only a fragment of winter, so the seasonal table below is a split of that single "
        "holdout, not a seasonal cross-validation.",
        "- No lagged-error features, and therefore no evidence about whether recent error "
        "carries information at this lead.",
        "- No hyperparameter search, no ensembling, no probabilistic output.",
        "- Direct and diffuse radiation, cloud cover, relative humidity and gusts are not "
        "modelled.",
        "",
    ]


def _results_table(results: list[MosResult]) -> str:
    rows = [
        "| variable | truth | unit | n train | n holdout | raw NWP MAE | climatology MAE | "
        "MOS MAE | skill vs raw |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in results:
        rows.append(
            f"| {item.variable} | {item.truth_source} | {item.unit} | {item.n_train:,} | "
            f"{item.n_holdout:,} | {item.raw_mae:.3f} | {item.climatology_mae:.3f} | "
            f"{item.mos_mae:.3f} | **{item.skill_pct:+.1f}%** |"
        )
    return "\n".join(rows)


def _bias_table(results: list[MosResult]) -> str:
    rows = ["| variable | raw NWP bias | MOS bias |", "|---|---|---|"]
    for item in results:
        rows.append(f"| {item.variable} | {item.raw_bias:+.3f} | {item.mos_bias:+.3f} |")
    return "\n".join(rows)


def _seasonal_table(item: MosResult) -> str:
    rows = ["| season | n | raw NWP MAE | MOS MAE | skill vs raw |", "|---|---|---|---|---|"]
    for record in item.seasonal.itertuples():
        rows.append(
            f"| {record.season} | {record.n:,} | {record.raw_mae:.3f} | "
            f"{record.mos_mae:.3f} | {record.skill_pct:+.1f}% |"
        )
    return "\n".join(rows)


def write_report(results: list[MosResult], generated: str, notes: list[str]) -> Path:
    lines = _preamble(results, generated)

    lines += ["## Result", ""]
    if not results:
        lines += ["_No variable produced a scorable split._", ""]
    else:
        lines += [_results_table(results), "", "Negative skill is an improvement.", ""]

        for item in results:
            if item.suspicious:
                lines += [
                    f"> **{item.variable}: {-item.skill_pct:.1f}% exceeds the "
                    f"{IRRADIANCE_SUSPICION_THRESHOLD:.0f}% threshold at which an irradiance "
                    "result is treated as a defect before it is treated as a result.** "
                    "Against a CAMS truth misaligned by one hour this same method returned "
                    "45.3%. Do not quote this figure until the truth alignment has been "
                    "re-checked.",
                    "",
                ]
            if not item.beats_climatology:
                lines += [
                    f"> **{item.variable}: the corrected forecast does not beat climatology** "
                    f"({item.mos_mae:.3f} against {item.climatology_mae:.3f}). A correction "
                    "that loses to the seasonal mean has not been shown to be useful.",
                    "",
                ]

        lines += [
            "### Bias",
            "",
            "Bias is what a MOS removes most reliably, so it is the clearest evidence that "
            "the correction did what it was asked to.",
            "",
            _bias_table(results),
            "",
            "### Skill by season within the holdout",
            "",
            "A split of the one holdout, not a cross-validation. Season labels describe "
            "which months of that single period each row covers.",
            "",
        ]
        for item in results:
            lines += [f"**{item.variable}**", "", _seasonal_table(item), ""]

    if notes:
        lines += ["## Notes from the run", ""] + [f"- {note}" for note in notes] + [""]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    return REPORT_PATH
