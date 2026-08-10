from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.config import AtlasConfig, TrajectoryConfig
from atlas.trajectory import TrajectoryField, compute_air_mass_origin

LATITUDES = np.arange(34.0, 62.1, 2.0)
LONGITUDES = np.arange(-10.0, 40.1, 2.0)


def _field(u: float, v: float, hours: int = 96, temperature: float = 5.0) -> TrajectoryField:
    """A spatially uniform, steady wind field, where displacement is exactly known."""
    times = list(pd.date_range("2026-08-05", periods=hours, freq="h", tz="UTC"))
    shape = (len(times), len(LATITUDES), len(LONGITUDES))
    return TrajectoryField(
        times=times,
        latitudes=LATITUDES,
        longitudes=LONGITUDES,
        wind_u_ms=np.full(shape, u, dtype=float),
        wind_v_ms=np.full(shape, v, dtype=float),
        temperature_c=np.full(shape, temperature, dtype=float),
        level_hpa=850,
        notes=[],
    )


def _config(hours: int = 24) -> AtlasConfig:
    return AtlasConfig(trajectory=TrajectoryConfig(hours=hours))


def test_uniform_westerly_places_the_origin_due_west_at_the_expected_distance():
    # 10 m/s for 24 hours is 864 km of travel.
    origin = compute_air_mass_origin(_field(u=10.0, v=0.0), _config(24))
    assert origin.available
    assert origin.hours_traced == pytest.approx(24.0, abs=0.1)
    assert origin.origin_sector == "west"
    assert origin.origin_distance_km == pytest.approx(864.0, rel=0.02)
    assert origin.path_length_km == pytest.approx(864.0, rel=0.02)
    assert origin.mean_speed_ms == pytest.approx(10.0, rel=0.02)
    # Every point should sit on the starting latitude for a purely zonal wind.
    assert all(point.latitude == pytest.approx(47.5316, abs=0.01) for point in origin.points)


def test_uniform_southerly_places_the_origin_due_south():
    # A wind blowing towards the north means the air came from the south.
    origin = compute_air_mass_origin(_field(u=0.0, v=8.0), _config(24))
    assert origin.origin_sector == "south"
    # 8 m/s northward for 24 hours is 691 km.
    assert origin.origin_distance_km == pytest.approx(691.0, rel=0.02)
    assert all(point.longitude == pytest.approx(21.6273, abs=0.01) for point in origin.points)


def test_hourly_points_are_recorded_along_the_path():
    origin = compute_air_mass_origin(_field(u=10.0, v=0.0), _config(12))
    assert len(origin.points) == 13  # arrival plus one per hour traced
    hours = [point.hours_before_arrival for point in origin.points]
    assert hours == sorted(hours)
    distances = [point.distance_from_city_km for point in origin.points]
    assert distances == sorted(distances)


def test_trajectory_stops_at_the_domain_edge_rather_than_extrapolating():
    # 30 m/s for 72 hours would travel far beyond the grid's western edge.
    origin = compute_air_mass_origin(_field(u=30.0, v=0.0, hours=120), _config(72))
    assert origin.left_domain
    assert origin.hours_traced < 72
    assert origin.points[-1].longitude >= LONGITUDES[0]
    assert any("edge of the wind domain" in note for note in origin.notes)


def test_temperature_change_is_reported_along_the_path():
    field = _field(u=10.0, v=0.0)
    # Make the west end colder, so air arriving from there warmed on the way.
    gradient = np.linspace(-10.0, 10.0, len(LONGITUDES))
    field.temperature_c[:, :, :] = gradient[np.newaxis, np.newaxis, :]
    origin = compute_air_mass_origin(field, _config(24))
    assert origin.temperature_change_c > 0
    assert "warming" in origin.summary


def test_calm_field_leaves_the_air_effectively_stationary():
    origin = compute_air_mass_origin(_field(u=0.0, v=0.0), _config(24))
    assert origin.origin_distance_km == pytest.approx(0.0, abs=0.5)
    assert "stationary" in origin.summary


def test_empty_field_reports_nothing_available():
    empty = TrajectoryField([], np.array([]), np.array([]), np.array([]), np.array([]), np.array([]), 850, [])
    origin = compute_air_mass_origin(empty, _config())
    assert not origin.available
    assert origin.notes
