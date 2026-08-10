"""Storm-relative wind parameters derived from the model profile.

The upper-air page already draws a hodograph but never reads anything off it.
These are the numbers a forecaster takes from that curve: how much the wind
turns and strengthens with height, where a right-moving storm would travel, and
how much streamwise vorticity it would ingest.

Everything is computed by MetPy from the same pressure-level profile the
sounding uses, so nothing here introduces a new data source. Heights are metres
above ground, taken from the lowest level in the profile.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from metpy import calc as mpcalc
from metpy.units import units

from atlas.profile import ModelProfile


# Depth in metres, and the label the pages use.
SHEAR_LAYERS: list[tuple[str, float]] = [
    ("0-1 km", 1000.0),
    ("0-3 km", 3000.0),
    ("0-6 km", 6000.0),
]
HELICITY_LAYERS: list[tuple[str, float]] = [
    ("0-1 km", 1000.0),
    ("0-3 km", 3000.0),
]

# Below this many levels with usable wind the hodograph is too coarse to
# integrate helicity over.
MINIMUM_WIND_LEVELS = 5


@dataclass(frozen=True)
class LayerShear:
    label: str
    depth_m: float
    u_ms: float
    v_ms: float
    magnitude_ms: float


@dataclass(frozen=True)
class LayerHelicity:
    label: str
    depth_m: float
    positive_m2_s2: float
    negative_m2_s2: float
    total_m2_s2: float


@dataclass(frozen=True)
class StormVector:
    label: str
    u_ms: float
    v_ms: float
    speed_ms: float
    direction_deg: float


@dataclass(frozen=True)
class StormKinematics:
    valid_time: str | None
    source: str
    shear: list[LayerShear]
    helicity: list[LayerHelicity]
    motions: list[StormVector]
    notes: list[str]

    @property
    def available(self) -> bool:
        return bool(self.shear or self.helicity or self.motions)

    def shear_for(self, label: str) -> LayerShear | None:
        for layer in self.shear:
            if layer.label == label:
                return layer
        return None

    def helicity_for(self, label: str) -> LayerHelicity | None:
        for layer in self.helicity:
            if layer.label == label:
                return layer
        return None

    def motion_for(self, label: str) -> StormVector | None:
        for motion in self.motions:
            if motion.label == label:
                return motion
        return None


def _vector(label: str, u: float, v: float) -> StormVector:
    speed = float(np.hypot(u, v))
    # Reported as the direction the vector points towards, which is how storm
    # motion is quoted, unlike the wind convention used elsewhere.
    direction = float((np.degrees(np.arctan2(u, v)) + 360.0) % 360.0)
    return StormVector(label=label, u_ms=float(u), v_ms=float(v), speed_ms=speed, direction_deg=direction)


def compute_storm_kinematics(profile: ModelProfile) -> StormKinematics:
    """Bulk shear, Bunkers storm motion and storm-relative helicity for the profile."""
    valid_time = profile.valid_time.isoformat() if profile.valid_time is not None else None
    empty = StormKinematics(
        valid_time=valid_time,
        source=profile.source,
        shear=[],
        helicity=[],
        motions=[],
        notes=["The model profile carried too few wind levels for storm-relative parameters."],
    )
    frame = profile.frame
    if frame is None or frame.empty:
        return empty
    needed = {"pressure_hpa", "wind_speed_ms", "wind_direction_deg", "geopotential_height_m"}
    if not needed.issubset(frame.columns):
        return empty

    ordered = (
        frame.dropna(subset=list(needed))
        .sort_values("pressure_hpa", ascending=False)
        .drop_duplicates(subset="pressure_hpa")
    )
    if len(ordered) < MINIMUM_WIND_LEVELS:
        return empty

    heights_asl = ordered["geopotential_height_m"].to_numpy(dtype=float)
    # MetPy's depth-based helpers measure from the first entry, so the profile is
    # expressed above ground rather than above sea level.
    height = (heights_asl - heights_asl[0]) * units.meter
    pressure = ordered["pressure_hpa"].to_numpy(dtype=float) * units.hPa
    speed = ordered["wind_speed_ms"].to_numpy(dtype=float) * units("m/s")
    direction = ordered["wind_direction_deg"].to_numpy(dtype=float) * units.degree
    u, v = mpcalc.wind_components(speed, direction)

    profile_depth = float(heights_asl[-1] - heights_asl[0])
    notes: list[str] = []

    motions: list[StormVector] = []
    right_u = right_v = None
    try:
        right, left, mean = mpcalc.bunkers_storm_motion(pressure, u, v, height)
        right_u = float(right[0].to("m/s").m)
        right_v = float(right[1].to("m/s").m)
        motions = [
            _vector("Right mover", right_u, right_v),
            _vector("Left mover", float(left[0].to("m/s").m), float(left[1].to("m/s").m)),
            _vector("0-6 km mean wind", float(mean[0].to("m/s").m), float(mean[1].to("m/s").m)),
        ]
    except Exception:
        notes.append("Bunkers storm motion could not be derived from this profile.")

    shear: list[LayerShear] = []
    for label, depth in SHEAR_LAYERS:
        if profile_depth < depth:
            continue
        try:
            shear_u, shear_v = mpcalc.bulk_shear(
                pressure, u, v, height=height, depth=depth * units.meter
            )
            magnitude = float(np.hypot(shear_u.to("m/s").m, shear_v.to("m/s").m))
            shear.append(
                LayerShear(
                    label=label,
                    depth_m=depth,
                    u_ms=float(shear_u.to("m/s").m),
                    v_ms=float(shear_v.to("m/s").m),
                    magnitude_ms=magnitude,
                )
            )
        except Exception:
            continue

    helicity: list[LayerHelicity] = []
    if right_u is not None and right_v is not None:
        for label, depth in HELICITY_LAYERS:
            if profile_depth < depth:
                continue
            try:
                positive, negative, total = mpcalc.storm_relative_helicity(
                    height,
                    u,
                    v,
                    depth=depth * units.meter,
                    storm_u=right_u * units("m/s"),
                    storm_v=right_v * units("m/s"),
                )
                helicity.append(
                    LayerHelicity(
                        label=label,
                        depth_m=depth,
                        positive_m2_s2=float(positive.m),
                        negative_m2_s2=float(negative.m),
                        total_m2_s2=float(total.m),
                    )
                )
            except Exception:
                continue

    if profile_depth < max(depth for _, depth in SHEAR_LAYERS):
        notes.append(
            f"The profile reaches {profile_depth / 1000.0:.1f} km above ground, "
            "so deeper layers are omitted rather than extrapolated."
        )
    notes.append(
        "Helicity is storm-relative to the Bunkers right mover and assumes that motion is realised."
    )
    return StormKinematics(
        valid_time=valid_time,
        source=profile.source,
        shear=shear,
        helicity=helicity,
        motions=motions,
        notes=notes,
    )
