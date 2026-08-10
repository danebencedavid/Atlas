"""Convective cells identified and tracked through the radar composite.

The radar pages replay imagery and integrate a rainfall proxy, but nothing reads
structure out of the frames. This labels contiguous areas above a reflectivity
threshold, follows them between frames, and reports how fast they moved, how
intense they became and how close they came to the city.

A deliberate omission: echo top and vertically integrated liquid are not here.
Both need a volume scan with multiple elevation angles, and this archive carries
a single two-dimensional composite, so neither can be derived honestly from it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import ndimage

from atlas.config import AtlasConfig
from atlas.hungaromet import RadarArchive

EARTH_RADIUS_KM = 6371.0088

# A cell is contiguous pixels at or above this reflectivity. 35 dBZ is the
# conventional convective threshold in a composite of this resolution.
CELL_THRESHOLD_DBZ = 35.0
# Smaller blobs are speckle at 1 km resolution rather than storms.
MINIMUM_CELL_AREA_KM2 = 15.0
# Frame-to-frame association limit. A cell moving faster than this is treated as
# a new cell rather than an implausible jump.
MAXIMUM_MATCH_SPEED_MS = 40.0

COVERAGE_CLASSES: list[tuple[str, float, float]] = [
    ("Light", 5.0, 20.0),
    ("Moderate", 20.0, 35.0),
    ("Convective", 35.0, 50.0),
    ("Intense", 50.0, np.inf),
]


@dataclass(frozen=True)
class CellObservation:
    time: str
    latitude: float
    longitude: float
    area_km2: float
    max_dbz: float
    mean_dbz: float
    distance_from_city_km: float


@dataclass(frozen=True)
class CellTrack:
    identifier: int
    observations: list[CellObservation]
    duration_hours: float
    mean_speed_ms: float
    bearing_deg: float
    peak_dbz: float
    peak_area_km2: float
    closest_approach_km: float

    @property
    def frames(self) -> int:
        return len(self.observations)


@dataclass(frozen=True)
class CoverageClass:
    label: str
    lower_dbz: float
    upper_dbz: float
    peak_area_km2: float
    mean_area_km2: float


@dataclass(frozen=True)
class RadarCellAnalysis:
    threshold_dbz: float
    tracks: list[CellTrack]
    coverage: list[CoverageClass]
    frames_analysed: int
    notes: list[str]

    @property
    def available(self) -> bool:
        return bool(self.tracks or self.coverage)

    @property
    def strongest(self) -> CellTrack | None:
        return max(self.tracks, key=lambda track: track.peak_dbz, default=None)

    @property
    def nearest(self) -> CellTrack | None:
        return min(self.tracks, key=lambda track: track.closest_approach_km, default=None)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    a = (
        np.sin((phi2 - phi1) / 2) ** 2
        + np.cos(phi1) * np.cos(phi2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    )
    return float(2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a)))


def _bearing_deg(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> float:
    phi1, phi2 = np.radians(from_lat), np.radians(to_lat)
    delta = np.radians(to_lon - from_lon)
    y = np.sin(delta) * np.cos(phi2)
    x = np.cos(phi1) * np.sin(phi2) - np.sin(phi1) * np.cos(phi2) * np.cos(delta)
    return float((np.degrees(np.arctan2(y, x)) + 360.0) % 360.0)


def _pixel_area_km2(latitudes: np.ndarray, longitudes: np.ndarray) -> float:
    if len(latitudes) < 2 or len(longitudes) < 2:
        return 1.0
    mean_latitude = float(np.mean(latitudes))
    lat_step_km = abs(float(latitudes[1] - latitudes[0])) * 111.32
    lon_step_km = abs(float(longitudes[1] - longitudes[0])) * 111.32 * np.cos(np.radians(mean_latitude))
    return float(lat_step_km * lon_step_km)


def analyse_radar_cells(
    radar: RadarArchive,
    config: AtlasConfig,
    threshold_dbz: float = CELL_THRESHOLD_DBZ,
) -> RadarCellAnalysis:
    """Identify convective cells frame by frame and link them into tracks."""
    empty = RadarCellAnalysis(
        threshold_dbz=threshold_dbz,
        tracks=[],
        coverage=[],
        frames_analysed=0,
        notes=["No radar frames were available for cell analysis."],
    )
    frames = radar.reflectivity_dbz
    if frames is None or frames.size == 0 or len(radar.times) == 0:
        return empty
    if frames.shape[0] != len(radar.times):
        return empty

    latitudes = radar.latitudes
    longitudes = radar.longitudes
    pixel_area = _pixel_area_km2(latitudes, longitudes)
    city_latitude = float(config.location.latitude)
    city_longitude = float(config.location.longitude)

    # Cells per frame, then linked between consecutive frames.
    per_frame: list[list[CellObservation]] = []
    coverage_areas: dict[str, list[float]] = {label: [] for label, _, _ in COVERAGE_CLASSES}
    for index, timestamp in enumerate(radar.times):
        field = frames[index]
        finite = np.isfinite(field)
        for label, lower, upper in COVERAGE_CLASSES:
            band = finite & (field >= lower) & (field < upper)
            coverage_areas[label].append(float(band.sum()) * pixel_area)

        mask = finite & (field >= threshold_dbz)
        labelled, count = ndimage.label(mask)
        observations: list[CellObservation] = []
        for cell_index in range(1, count + 1):
            selection = labelled == cell_index
            area = float(selection.sum()) * pixel_area
            if area < MINIMUM_CELL_AREA_KM2:
                continue
            rows, columns = np.nonzero(selection)
            weights = field[selection]
            # Reflectivity-weighted centroid, so the position follows the core.
            weight_total = float(weights.sum())
            if weight_total <= 0:
                continue
            latitude = float(np.average(latitudes[rows], weights=weights))
            longitude = float(np.average(longitudes[columns], weights=weights))
            observations.append(
                CellObservation(
                    time=pd.Timestamp(timestamp).isoformat(),
                    latitude=latitude,
                    longitude=longitude,
                    area_km2=area,
                    max_dbz=float(weights.max()),
                    mean_dbz=float(weights.mean()),
                    distance_from_city_km=_haversine_km(city_latitude, city_longitude, latitude, longitude),
                )
            )
        per_frame.append(observations)

    # Link frame to frame by nearest centroid, subject to a plausible speed.
    open_tracks: list[list[CellObservation]] = []
    closed_tracks: list[list[CellObservation]] = []
    previous_time: pd.Timestamp | None = None
    for index, observations in enumerate(per_frame):
        timestamp = pd.Timestamp(radar.times[index])
        gap_seconds = (timestamp - previous_time).total_seconds() if previous_time is not None else 0.0
        reach_km = MAXIMUM_MATCH_SPEED_MS * max(gap_seconds, 0.0) / 1000.0
        unmatched = list(observations)
        still_open: list[list[CellObservation]] = []
        for track in open_tracks:
            last = track[-1]
            best = None
            best_distance = reach_km
            for candidate in unmatched:
                distance = _haversine_km(last.latitude, last.longitude, candidate.latitude, candidate.longitude)
                if distance <= best_distance:
                    best, best_distance = candidate, distance
            if best is not None:
                track.append(best)
                unmatched.remove(best)
                still_open.append(track)
            else:
                closed_tracks.append(track)
        open_tracks = still_open + [[observation] for observation in unmatched]
        previous_time = timestamp
    closed_tracks.extend(open_tracks)

    tracks: list[CellTrack] = []
    for identifier, observations in enumerate(sorted(closed_tracks, key=len, reverse=True), start=1):
        if len(observations) < 2:
            continue
        first, last = observations[0], observations[-1]
        duration_hours = (pd.Timestamp(last.time) - pd.Timestamp(first.time)).total_seconds() / 3600.0
        displacement_km = _haversine_km(first.latitude, first.longitude, last.latitude, last.longitude)
        speed = (displacement_km * 1000.0 / (duration_hours * 3600.0)) if duration_hours > 0 else 0.0
        tracks.append(
            CellTrack(
                identifier=identifier,
                observations=observations,
                duration_hours=duration_hours,
                mean_speed_ms=speed,
                bearing_deg=_bearing_deg(first.latitude, first.longitude, last.latitude, last.longitude),
                peak_dbz=max(observation.max_dbz for observation in observations),
                peak_area_km2=max(observation.area_km2 for observation in observations),
                closest_approach_km=min(observation.distance_from_city_km for observation in observations),
            )
        )
    tracks.sort(key=lambda track: track.peak_dbz, reverse=True)

    coverage = [
        CoverageClass(
            label=label,
            lower_dbz=lower,
            upper_dbz=upper,
            peak_area_km2=float(np.max(coverage_areas[label])) if coverage_areas[label] else 0.0,
            mean_area_km2=float(np.mean(coverage_areas[label])) if coverage_areas[label] else 0.0,
        )
        for label, lower, upper in COVERAGE_CLASSES
    ]

    notes = [
        f"Cells are contiguous areas at or above {threshold_dbz:.0f} dBZ covering at least "
        f"{MINIMUM_CELL_AREA_KM2:.0f} km², tracked by reflectivity-weighted centroid between frames.",
        "Echo top and vertically integrated liquid are not derived: both need a volume scan "
        "with multiple elevation angles, and this archive holds a single composite.",
    ]
    if radar.times and len(radar.times) > 1:
        step_minutes = (pd.Timestamp(radar.times[1]) - pd.Timestamp(radar.times[0])).total_seconds() / 60.0
        notes.append(
            f"Frames are {step_minutes:.0f} minutes apart, so motion is resolved only to that cadence."
        )
    return RadarCellAnalysis(
        threshold_dbz=threshold_dbz,
        tracks=tracks,
        coverage=coverage,
        frames_analysed=len(per_frame),
        notes=notes,
    )
