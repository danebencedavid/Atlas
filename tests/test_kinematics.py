from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.kinematics import compute_storm_kinematics
from atlas.profile import ModelProfile

LEVELS = [1000, 925, 850, 700, 600, 500, 400]
HEIGHTS = [110.0, 780.0, 1500.0, 3100.0, 4400.0, 5700.0, 7200.0]


def _profile(directions, speeds) -> ModelProfile:
    frame = pd.DataFrame(
        {
            "pressure_hpa": [float(level) for level in LEVELS],
            "geopotential_height_m": HEIGHTS,
            "wind_speed_ms": speeds,
            "wind_direction_deg": directions,
            "temperature_c": [20.0, 15.0, 10.0, 0.0, -8.0, -18.0, -32.0],
            "dew_point_c": [15.0, 10.0, 5.0, -5.0, -15.0, -28.0, -45.0],
        }
    )
    return ModelProfile(frame, pd.Timestamp("2026-08-09T12:00Z"), "test profile", {}, [])


def _straight() -> ModelProfile:
    """Constant westerly direction, speed rising linearly to 30 m/s at 6 km."""
    return _profile([270.0] * len(LEVELS), np.interp(HEIGHTS, [110.0, 6110.0], [0.0, 30.0]))


def _curved() -> ModelProfile:
    """Direction veering through the lowest 3 km, which adds streamwise vorticity."""
    directions = np.interp(HEIGHTS, [110.0, 3100.0, 7200.0], [140.0, 250.0, 280.0])
    return _profile(directions, np.interp(HEIGHTS, [110.0, 6110.0], [5.0, 28.0]))


def test_shear_magnitude_equals_the_speed_change_on_a_straight_hodograph():
    kinematics = compute_storm_kinematics(_straight())
    # Direction never changes, so the shear vector is the speed difference alone.
    assert kinematics.shear_for("0-1 km").magnitude_ms == pytest.approx(5.0, abs=0.05)
    assert kinematics.shear_for("0-3 km").magnitude_ms == pytest.approx(15.0, abs=0.05)
    assert kinematics.shear_for("0-6 km").magnitude_ms == pytest.approx(28.5, abs=0.05)
    # A westerly profile shears eastward, with no north-south component.
    assert kinematics.shear_for("0-6 km").u_ms > 0
    assert kinematics.shear_for("0-6 km").v_ms == pytest.approx(0.0, abs=0.05)


def test_bunkers_movers_straddle_the_mean_wind():
    kinematics = compute_storm_kinematics(_straight())
    mean = kinematics.motion_for("0-6 km mean wind")
    right = kinematics.motion_for("Right mover")
    left = kinematics.motion_for("Left mover")
    assert mean is not None and right is not None and left is not None
    # A westerly wind carries storms towards the east.
    assert mean.direction_deg == pytest.approx(90.0, abs=1.0)
    # The movers deviate to either side by the same amount.
    assert right.direction_deg > mean.direction_deg > left.direction_deg
    assert (right.direction_deg - mean.direction_deg) == pytest.approx(
        mean.direction_deg - left.direction_deg, abs=1.0
    )


def test_curvature_increases_storm_relative_helicity():
    straight = compute_storm_kinematics(_straight())
    curved = compute_storm_kinematics(_curved())
    assert curved.helicity_for("0-3 km").total_m2_s2 > straight.helicity_for("0-3 km").total_m2_s2
    # Veering with height gives positive, right-mover-favourable helicity.
    assert curved.helicity_for("0-1 km").total_m2_s2 > 0
    assert curved.helicity_for("0-3 km").total_m2_s2 > 0


def test_layers_deeper_than_the_profile_are_omitted_not_extrapolated():
    shallow = _profile([270.0] * len(LEVELS), [10.0] * len(LEVELS))
    shallow.frame["geopotential_height_m"] = [110.0, 400.0, 700.0, 1100.0, 1500.0, 1900.0, 2300.0]
    kinematics = compute_storm_kinematics(shallow)
    labels = {layer.label for layer in kinematics.shear}
    assert "0-1 km" in labels
    assert "0-6 km" not in labels
    assert any("omitted rather than extrapolated" in note for note in kinematics.notes)


def test_profile_without_wind_reports_nothing_available():
    profile = _straight()
    profile.frame["wind_speed_ms"] = np.nan
    kinematics = compute_storm_kinematics(profile)
    assert not kinematics.available
    assert kinematics.notes


def test_empty_profile_is_handled():
    kinematics = compute_storm_kinematics(ModelProfile(pd.DataFrame(), None, "none", {}, []))
    assert not kinematics.available
    assert kinematics.valid_time is None
