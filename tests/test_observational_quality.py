"""Completeness gating for the observational inputs.

These cover the defect that let five consecutive editions publish with the
headline day at 8% station coverage: the quality gate validated the gridded
frame only, so the station, radar and lightning inputs had no threshold at all.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from atlas.hungaromet import LightningArchive, RadarArchive, StationObservations
from atlas.quality import (
    ObservationFreshnessError,
    PublicationIntegrityError,
    assert_required_input_coverage,
    assert_observations_fresh,
    observation_shortfall_hours,
    validate_lightning_period,
    validate_radar_period,
    validate_station_period,
)

TZ = "Europe/Budapest"
START, END = date(2026, 8, 14), date(2026, 8, 16)
# The window runs 2026-08-13 22:00Z to 2026-08-16 22:00Z.
WINDOW_START = pd.Timestamp("2026-08-13 22:00", tz="UTC")
WINDOW_END = pd.Timestamp("2026-08-16 22:00", tz="UTC")


def _station(last: pd.Timestamp) -> StationObservations:
    times = pd.date_range(WINDOW_START, last, freq="10min", tz="UTC", inclusive="left")
    return StationObservations(pd.DataFrame({"time": times}), 64711, "Debrecen Airport", [])


def _radar(first: pd.Timestamp) -> RadarArchive:
    times = list(pd.date_range(first, WINDOW_END, freq="30min", tz="UTC", inclusive="left"))
    import numpy as np

    return RadarArchive(times, np.array([]), np.array([]), np.empty((0, 0, 0)), np.empty((0, 0)), pd.DataFrame(), [])


def test_station_missing_its_trailing_day_fails_the_gate():
    """The exact published defect: two good days and a nearly empty third."""
    # Data stops at the end of 2026-08-15 local, as the 05:15 build saw it.
    coverage = validate_station_period(
        _station(pd.Timestamp("2026-08-15 22:00", tz="UTC")), START, END, TZ
    )
    assert not coverage.ok
    assert coverage.available
    assert coverage.observed == 288
    assert coverage.expected == 432
    assert coverage.coverage == pytest.approx(2 / 3, abs=0.01)

    final_day = coverage.per_day.iloc[-1]
    assert str(final_day["local_day"]) == "2026-08-16"
    assert final_day["observed"] == 0
    # The thin day must be named, not averaged away.
    assert any("2026-08-16" in note for note in coverage.notes)


def test_fully_observed_station_passes():
    coverage = validate_station_period(_station(WINDOW_END), START, END, TZ)
    assert coverage.ok
    assert coverage.observed == 432
    assert (coverage.per_day["observed"] == 144).all()


def test_a_thin_middle_day_cannot_hide_inside_a_passing_aggregate():
    station = _station(WINDOW_END)
    local_day = station.frame["time"].dt.tz_convert(TZ).dt.date
    middle_day = date(2026, 8, 15)
    drop = station.frame.index[local_day == middle_day][:21]
    station = StationObservations(
        station.frame.drop(drop), station.station_id, station.station_name, station.notes
    )

    coverage = validate_station_period(station, START, END, TZ)

    assert coverage.coverage == pytest.approx(411 / 432)
    assert not coverage.ok
    assert any("2026-08-15" in note for note in coverage.notes)
    with pytest.raises(PublicationIntegrityError, match="2026-08-15"):
        assert_required_input_coverage([coverage])


def test_required_coverage_fails_if_the_station_check_is_missing():
    with pytest.raises(PublicationIntegrityError, match="was not evaluated"):
        assert_required_input_coverage([])


def test_duplicate_station_rows_cannot_mask_a_missing_interval():
    station = _station(WINDOW_END)
    frame = station.frame.drop(index=100)
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    station = StationObservations(frame, station.station_id, station.station_name, station.notes)

    coverage = validate_station_period(station, START, END, TZ, minimum_coverage=1.0)

    assert coverage.observed == 431
    assert not coverage.ok


def test_station_daily_expectation_respects_the_dst_clock_change():
    dst_day = date(2026, 3, 29)
    start = pd.Timestamp("2026-03-29 00:00", tz=TZ).tz_convert("UTC")
    end = pd.Timestamp("2026-03-30 00:00", tz=TZ).tz_convert("UTC")
    station = StationObservations(
        pd.DataFrame({"time": pd.date_range(start, end, freq="10min", inclusive="left")}),
        64711,
        "Debrecen Airport",
        [],
    )

    coverage = validate_station_period(station, dst_day, dst_day, TZ)

    assert coverage.expected == 138
    assert coverage.per_day.iloc[0]["expected"] == 138
    assert coverage.ok


def test_radar_missing_leading_frames_is_judged_against_what_is_retained():
    """Radar fails at the opposite end, and for a structural reason."""
    # Build time is just after the window closes; retention reaches back 71 h.
    now = WINDOW_END + pd.Timedelta(hours=7)
    first_available = now - pd.Timedelta(hours=71)
    coverage = validate_radar_period(
        _radar(first_available), START, END, TZ, retention_hours=71.0, now=now
    )
    # Gating on the full 144-frame window would fail permanently on a known limit.
    assert coverage.expected < 144
    assert coverage.ok
    assert coverage.structural_note is not None
    assert "structurally unavailable" in coverage.structural_note


def test_radar_below_threshold_within_the_reachable_window_fails():
    now = WINDOW_END + pd.Timedelta(hours=1)
    # Half the reachable frames are absent, which is a real outage, not retention.
    sparse = _radar(WINDOW_END - pd.Timedelta(hours=12))
    coverage = validate_radar_period(sparse, START, END, TZ, retention_hours=71.0, now=now)
    assert not coverage.ok
    assert any("below the" in note for note in coverage.notes)


def test_failed_lightning_fetch_is_not_reported_as_zero_strikes():
    failed = LightningArchive(pd.DataFrame(), pd.DataFrame(), ["unavailable"], available=False)
    coverage = validate_lightning_period(failed, START, END, TZ)
    assert not coverage.ok
    assert not coverage.available
    assert any("not a report of zero strikes" in note for note in coverage.notes)


def test_genuinely_quiet_period_is_reported_as_an_observation():
    quiet = LightningArchive(pd.DataFrame(), pd.DataFrame(), ["none detected"], available=True)
    coverage = validate_lightning_period(quiet, START, END, TZ)
    # Zero strikes is a valid observation and must pass.
    assert coverage.ok
    assert coverage.available
    assert coverage.observed == 0
    assert any("recorded no strikes" in note for note in coverage.notes)


def test_partial_lightning_days_are_disclosed_even_when_available():
    partial = LightningArchive(
        pd.DataFrame({"time": [WINDOW_START]}), pd.DataFrame(), [], available=True, missing_days=2
    )
    coverage = validate_lightning_period(partial, START, END, TZ)
    assert coverage.ok
    assert any("2 daily lightning file" in note for note in coverage.notes)


def test_freshness_check_names_the_shortfall():
    """The load-bearing guarantee: the data, not the build schedule."""
    stale = pd.Timestamp("2026-08-15 23:50", tz="UTC")
    shortfall = observation_shortfall_hours(stale, START, END, TZ)
    assert shortfall == pytest.approx(22.17, abs=0.05)
    with pytest.raises(ObservationFreshnessError, match="22.2 h before the reporting window closes"):
        assert_observations_fresh(stale, START, END, TZ, tolerance_hours=2.0)


def test_fresh_observations_pass_the_check():
    fresh = pd.Timestamp("2026-08-16 23:50", tz="UTC")
    # Past the window end, so no shortfall at all.
    assert assert_observations_fresh(fresh, START, END, TZ, tolerance_hours=2.0) == 0.0


def test_missing_observations_fail_the_freshness_check():
    with pytest.raises(ObservationFreshnessError, match="No station observations"):
        assert_observations_fresh(None, START, END, TZ)


def test_naive_timestamps_are_rejected():
    with pytest.raises(AssertionError, match="timezone-aware"):
        observation_shortfall_hours(pd.Timestamp("2026-08-16 12:00"), START, END, TZ)


def test_published_text_distinguishes_unavailable_lightning_from_zero():
    """The README promises optional-source failures stay explicitly unavailable.

    An edition that prints "0 lightning event(s)" for a failed archive states an
    observation that was never made, and the false reading is the reassuring one.
    """
    from atlas.site import _lightning_phrase

    quiet = LightningArchive(pd.DataFrame(), pd.DataFrame(), [], available=True)
    failed = LightningArchive(pd.DataFrame(), pd.DataFrame(), [], available=False)

    assert _lightning_phrase(quiet, 0) == "0 lightning event(s)"
    phrase = _lightning_phrase(failed, 0)
    assert "unavailable" in phrase
    assert "not zero strikes" in phrase
    assert "0 lightning event(s)" not in phrase


def test_unavailable_radar_is_not_published_as_an_absence_of_echo():
    import numpy as np

    from atlas.site import _radar_peak_phrase

    failed = RadarArchive([], np.array([]), np.array([]), np.empty((0, 0, 0)),
                          np.empty((0, 0)), pd.DataFrame(), [], available=False)
    working = RadarArchive([], np.array([]), np.array([]), np.empty((0, 0, 0)),
                           np.empty((0, 0)), pd.DataFrame(), [], available=True)
    assert "unavailable radar archive" in _radar_peak_phrase(failed, float("nan"))
    assert "not an absence of echo" in _radar_peak_phrase(failed, float("nan"))
    assert "maximum sampled radar reflectivity" in _radar_peak_phrase(working, 47.0)


def test_frontal_analysis_without_a_series_says_none_was_attempted():
    from atlas.fronts import FrontAnalysis
    from atlas.site import _front_phrase

    # detect_fronts returns this when there is no surface series to search.
    unattempted = FrontAnalysis([], pd.DataFrame(), [], available=False)
    searched = FrontAnalysis([], pd.DataFrame(), [], available=True)
    assert "none was attempted" in _front_phrase(unattempted)
    assert _front_phrase(searched) == "0 objective frontal passage candidate(s)"


def test_phenomena_ledger_names_the_inputs_it_lacked():
    from atlas.phenomena import PhenomenaAnalysis
    from atlas.site import _phenomena_phrase

    complete = PhenomenaAnalysis([], [])
    degraded = PhenomenaAnalysis([], [], degraded_inputs=["radar", "lightning"])
    assert _phenomena_phrase(complete) == "0 objective phenomenon candidate(s)"
    phrase = _phenomena_phrase(degraded)
    assert "radar, lightning" in phrase
    assert "missing evidence rather than a quiet period" in phrase
