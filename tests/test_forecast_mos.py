from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.forecast_mos import (
    FEATURES,
    HOLDOUT_START,
    IRRADIANCE_SUSPICION_THRESHOLD,
    LEAD_HOURS,
    TARGET_MODEL,
    MosResult,
    build_design,
    fit_and_score,
)


def _archive(hours: int = 20000) -> pd.DataFrame:
    """Two models, one variable, one lead, spanning the split."""
    times = pd.date_range("2024-01-22", periods=hours, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    base = 10.0 + 5.0 * np.sin(2 * np.pi * times.hour / 24.0)
    rows = []
    for model, offset in ((TARGET_MODEL, 0.0), ("ecmwf_ifs025", 0.3)):
        rows.append(
            pd.DataFrame(
                {
                    "valid_time_utc": times,
                    "lead_time_hours": LEAD_HOURS,
                    "model": model,
                    "variable": "temperature_2m",
                    "value": base + offset + rng.normal(0, 0.5, hours),
                    "retrieved_at": times,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def _truth(archive: pd.DataFrame) -> pd.DataFrame:
    times = archive["valid_time_utc"].drop_duplicates().sort_values()
    rng = np.random.default_rng(1)
    base = 10.0 + 5.0 * np.sin(2 * np.pi * times.dt.hour / 24.0)
    return pd.DataFrame(
        {
            "valid_time_utc": times.to_numpy(),
            "variable": "temperature_2m",
            # A standing bias the correction should be able to find.
            "observed": base.to_numpy() + 1.5 + rng.normal(0, 0.4, len(times)),
            "truth_source": "station",
        }
    )


def test_every_feature_is_knowable_when_the_forecast_is_issued():
    """The cutoff is the whole guarantee, so it is asserted as a list, not a habit.

    Any feature derived from an observation, or from an error, would let the model
    learn from information that does not exist at inference time. The failure is
    silent: the score simply comes out better than it can ever be in operation.
    """
    assert FEATURES == ["forecast", "spread", "hour_sin", "hour_cos", "doy_sin", "doy_cos"]
    archive = _archive()
    design = build_design(archive, _truth(archive), "temperature_2m", "station")
    for name in FEATURES:
        assert name in design
    # Nothing that reads the truth may reach the feature matrix.
    assert not {"observed", "residual"} & set(FEATURES)


def test_the_target_is_the_residual_not_the_observation():
    archive = _archive()
    design = build_design(archive, _truth(archive), "temperature_2m", "station")
    expected = design["observed"] - design["forecast"]
    assert np.allclose(design["residual"], expected)


def test_training_and_holdout_never_overlap():
    archive = _archive()
    design = build_design(archive, _truth(archive), "temperature_2m", "station")
    train = design[design["valid_time_utc"] < HOLDOUT_START]
    holdout = design[design["valid_time_utc"] >= HOLDOUT_START]
    assert len(train) and len(holdout)
    assert train["valid_time_utc"].max() < HOLDOUT_START <= holdout["valid_time_utc"].min()
    # Split on time, not at random: the two sides share no hour at all.
    assert not set(train["valid_time_utc"]) & set(holdout["valid_time_utc"])


def test_a_standing_bias_is_removed_and_the_score_is_reported_against_raw():
    archive = _archive()
    design = build_design(archive, _truth(archive), "temperature_2m", "station")
    result = fit_and_score(design, "temperature_2m", "station", "degC")
    assert result is not None
    # The synthetic truth sits 1.5 above the forecast; raw bias should show it.
    assert result.raw_bias == pytest.approx(-1.5, abs=0.15)
    assert abs(result.mos_bias) < 0.3
    assert result.skill_pct < 0  # negative is an improvement
    assert result.n_train > result.n_holdout


def test_a_split_too_small_to_score_returns_nothing_rather_than_a_number():
    archive = _archive(hours=300)
    design = build_design(archive, _truth(archive), "temperature_2m", "station")
    assert fit_and_score(design, "temperature_2m", "station", "degC") is None


def _result(mos_mae: float, raw_mae: float, variable: str, climatology_mae: float = 999.0) -> MosResult:
    return MosResult(
        variable=variable,
        truth_source="cams",
        unit="W/m2",
        n_train=1,
        n_holdout=1,
        holdout_start=HOLDOUT_START,
        holdout_end=HOLDOUT_START,
        raw_mae=raw_mae,
        climatology_mae=climatology_mae,
        mos_mae=mos_mae,
        raw_bias=0.0,
        mos_bias=0.0,
        seasonal=pd.DataFrame(),
    )


def test_a_large_irradiance_gain_is_flagged_as_a_defect_before_a_result():
    """Against a CAMS truth misaligned by one hour this method returned 45.3%.

    Nearly all of it was the model learning to undo a parser bug. A large
    irradiance number is therefore evidence of a defect until it is ruled out.
    """
    assert _result(50.0, 100.0, "shortwave_radiation").suspicious
    assert not _result(96.0, 100.0, "shortwave_radiation").suspicious
    # The threshold applies to irradiance only: wind genuinely does this well.
    assert not _result(69.0, 100.0, "wind_speed_10m").suspicious
    assert IRRADIANCE_SUSPICION_THRESHOLD == 15.0


def test_losing_to_climatology_is_detectable():
    assert _result(50.0, 100.0, "wind_speed_10m", climatology_mae=60.0).beats_climatology
    assert not _result(50.0, 100.0, "wind_speed_10m", climatology_mae=40.0).beats_climatology
