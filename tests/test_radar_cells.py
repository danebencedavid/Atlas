from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.config import AtlasConfig
from atlas.hungaromet import RadarArchive
from atlas.radar_cells import analyse_radar_cells

# A 1 km-ish grid centred near Debrecen.
LATITUDES = np.arange(46.5, 48.6, 0.02)
LONGITUDES = np.arange(20.5, 22.8, 0.02)


def _archive(centres: list[tuple[float, float]], peak_dbz: float = 52.0, radius_deg: float = 0.10,
             step_minutes: int = 30) -> RadarArchive:
    """Frames holding one Gaussian blob, moving through the given centres."""
    times = [pd.Timestamp("2026-08-07T12:00Z") + pd.Timedelta(minutes=step_minutes * i)
             for i in range(len(centres))]
    lon_grid, lat_grid = np.meshgrid(LONGITUDES, LATITUDES)
    frames = np.full((len(centres), len(LATITUDES), len(LONGITUDES)), np.nan)
    for index, (latitude, longitude) in enumerate(centres):
        distance = np.hypot(lat_grid - latitude, lon_grid - longitude)
        frames[index] = peak_dbz * np.exp(-(distance / radius_deg) ** 2)
    return RadarArchive(
        times=times,
        latitudes=LATITUDES,
        longitudes=LONGITUDES,
        reflectivity_dbz=frames,
        accumulation_mm=np.zeros((len(LATITUDES), len(LONGITUDES))),
        timeline=pd.DataFrame(),
        notes=[],
    )


def test_a_single_moving_blob_is_tracked_as_one_cell():
    # Due east along 47.5 N, 0.2 degrees per 30-minute frame.
    centres = [(47.5, 21.0), (47.5, 21.2), (47.5, 21.4), (47.5, 21.6)]
    analysis = analyse_radar_cells(_archive(centres), AtlasConfig())
    assert analysis.available
    assert len(analysis.tracks) == 1
    track = analysis.tracks[0]
    assert track.frames == 4
    assert track.duration_hours == pytest.approx(1.5, abs=0.01)
    # 0.6 degrees of longitude at 47.5 N is about 45 km, over 1.5 hours.
    assert track.mean_speed_ms == pytest.approx(8.4, rel=0.15)
    assert track.bearing_deg == pytest.approx(90.0, abs=3.0)
    assert track.peak_dbz == pytest.approx(52.0, abs=0.5)


def test_closest_approach_to_the_city_is_reported():
    # The blob passes directly over Debrecen in the middle frame.
    centres = [(47.5316, 21.2), (47.5316, 21.6273), (47.5316, 22.0)]
    analysis = analyse_radar_cells(_archive(centres), AtlasConfig())
    assert analysis.tracks[0].closest_approach_km == pytest.approx(0.0, abs=3.0)


def test_two_separated_blobs_are_two_tracks():
    times = [pd.Timestamp("2026-08-07T12:00Z"), pd.Timestamp("2026-08-07T12:30Z")]
    lon_grid, lat_grid = np.meshgrid(LONGITUDES, LATITUDES)
    frames = np.full((2, len(LATITUDES), len(LONGITUDES)), np.nan)
    for index in range(2):
        offset = 0.15 * index
        west = 50.0 * np.exp(-(np.hypot(lat_grid - 46.9, lon_grid - (20.9 + offset)) / 0.08) ** 2)
        east = 50.0 * np.exp(-(np.hypot(lat_grid - 48.2, lon_grid - (22.4 + offset)) / 0.08) ** 2)
        frames[index] = np.maximum(west, east)
    archive = RadarArchive(times, LATITUDES, LONGITUDES, frames,
                           np.zeros((len(LATITUDES), len(LONGITUDES))), pd.DataFrame(), [])
    analysis = analyse_radar_cells(archive, AtlasConfig())
    assert len(analysis.tracks) == 2


def test_an_implausible_jump_starts_a_new_track_rather_than_linking():
    # Two frames 30 minutes apart with the blob 200 km away: over 40 m/s, so no link.
    centres = [(46.7, 20.7), (48.4, 22.6)]
    analysis = analyse_radar_cells(_archive(centres), AtlasConfig())
    # Neither single-frame track survives the two-observation minimum.
    assert analysis.tracks == []


def test_coverage_classes_report_area_by_intensity():
    analysis = analyse_radar_cells(_archive([(47.5, 21.6)] * 2), AtlasConfig())
    labels = [item.label for item in analysis.coverage]
    assert labels == ["Light", "Moderate", "Convective", "Intense"]
    assert all(item.peak_area_km2 >= item.mean_area_km2 for item in analysis.coverage)
    # A 52 dBZ core must register area in the intense band.
    intense = next(item for item in analysis.coverage if item.label == "Intense")
    assert intense.peak_area_km2 > 0


def test_weak_echo_produces_no_cells():
    analysis = analyse_radar_cells(_archive([(47.5, 21.4), (47.5, 21.6)], peak_dbz=18.0), AtlasConfig())
    assert analysis.tracks == []
    assert analysis.frames_analysed == 2


def test_echo_top_and_vil_are_explicitly_not_claimed():
    analysis = analyse_radar_cells(_archive([(47.5, 21.4), (47.5, 21.6)]), AtlasConfig())
    assert any("volume scan" in note for note in analysis.notes)


def test_empty_archive_is_handled():
    archive = RadarArchive([], np.array([]), np.array([]), np.empty((0, 0, 0)),
                           np.empty((0, 0)), pd.DataFrame(), [])
    analysis = analyse_radar_cells(archive, AtlasConfig())
    assert not analysis.available
    assert analysis.frames_analysed == 0
