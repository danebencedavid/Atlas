from __future__ import annotations

import math
from dataclasses import dataclass

from atlas.anomalies import Anomaly
from atlas.climatology import ClimateReference
from atlas.energy import PhysicalEnergy
from atlas.fronts import FrontAnalysis
from atlas.hungaromet import LightningArchive, RadarArchive
from atlas.land import LandSurfaceAnalysis
from atlas.phenomena import PhenomenaAnalysis
from atlas.profile import ModelProfile
from atlas.regimes import RegimeClassification


@dataclass(frozen=True)
class StoryFact:
    label: str
    value: str


@dataclass(frozen=True)
class StoryNode:
    id: str
    domain: str
    domain_label: str
    label: str
    reading: str
    facts: list[StoryFact]
    source: str
    x: float
    y: float


@dataclass(frozen=True)
class StoryEdge:
    source: str
    target: str
    relationship: str


@dataclass(frozen=True)
class WeatherStory:
    title: str
    briefing: str
    nodes: list[StoryNode]
    edges: list[StoryEdge]


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: object, unit: str = "", digits: int = 1, signed: bool = False) -> str:
    number = _finite(value)
    if number is None:
        return "Unavailable"
    prefix = "+" if signed and number > 0 else ""
    suffix = f" {unit}" if unit else ""
    return f"{prefix}{number:.{digits}f}{suffix}"


def _anomaly(anomalies: list[Anomaly], metric: str) -> Anomaly | None:
    return next((item for item in anomalies if item.metric == metric), None)


def _rank(climate: ClimateReference, metric: str) -> str:
    value = _finite(climate.full_record_percentiles.get(metric))
    if value is None:
        return "Unavailable"
    rank = int(round(value))
    suffix = (
        "th"
        if 10 <= rank % 100 <= 20
        else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    )
    return f"{rank}{suffix} percentile"


def _thermal_label(anomaly: float | None) -> str:
    if anomaly is None:
        return "Thermal character unavailable"
    if anomaly >= 4:
        return "Exceptional warmth"
    if anomaly >= 2:
        return "Marked warmth"
    if anomaly <= -4:
        return "Exceptional cold"
    if anomaly <= -2:
        return "Marked cold"
    return "Near-normal temperature"


def _sky_label(cloud_rank: float | None, precipitation: float | None) -> str:
    if cloud_rank is not None and cloud_rank <= 20 and (precipitation or 0.0) <= 1.0:
        return "Exceptionally clear and dry"
    if cloud_rank is not None and cloud_rank >= 80:
        return "Cloud-dominated period"
    if precipitation is not None and precipitation >= 10:
        return "Wet surface weather"
    return "Mixed sky and precipitation"


def _yield_label(kind: str, capacity_factor: float | None) -> str:
    if capacity_factor is None:
        return f"{kind} yield unavailable"
    if kind == "PV":
        adjective = "Strong" if capacity_factor >= 20 else "Moderate" if capacity_factor >= 10 else "Limited"
    else:
        adjective = "Strong" if capacity_factor >= 30 else "Moderate" if capacity_factor >= 15 else "Limited"
    return f"{adjective} {kind} weather yield"


def build_weather_story(
    regime: RegimeClassification,
    current_metrics: dict[str, float],
    anomalies: list[Anomaly],
    climate: ClimateReference,
    fronts: FrontAnalysis,
    phenomena: PhenomenaAnalysis,
    profile: ModelProfile,
    land: LandSurfaceAnalysis,
    physical_energy: PhysicalEnergy,
    lightning: LightningArchive,
    radar: RadarArchive,
    lightning_radius_km: float,
) -> WeatherStory:
    temperature = _anomaly(anomalies, "temperature_mean_c")
    precipitation = _anomaly(anomalies, "precipitation_total_mm")
    cloud = _anomaly(anomalies, "cloud_cover_mean_pct")
    radiation = _anomaly(anomalies, "shortwave_total_wh_m2")

    temperature_anomaly = _finite(temperature.anomaly if temperature else None)
    cloud_rank = _finite(climate.full_record_percentiles.get("cloud_cover_mean_pct"))
    precipitation_total = _finite(current_metrics.get("precipitation_total_mm"))
    radar_max = (
        _finite(radar.timeline["domain_max_dbz"].max())
        if not radar.timeline.empty and "domain_max_dbz" in radar.timeline
        else None
    )
    thunder_events = [event for event in phenomena.events if event.kind == "Thunderstorm"]
    inversion_events = [
        event for event in phenomena.events if event.kind == "Nocturnal low-level inversion"
    ]
    pbl_height = _finite(profile.diagnostics.get("boundary_layer_height_m"))
    cape = _finite(profile.diagnostics.get("surface_based_cape_j_kg"))

    if thunder_events or len(lightning.frame):
        event_label = "Regional convective activity"
        event_reading = (
            "Lightning and radar establish convection inside the study radius; "
            "local precipitation is retained separately."
        )
        event_source = "HungaroMet LINET, composite radar and the objective phenomena ledger"
    elif phenomena.events:
        event_label = "Observed weather phenomena"
        event_reading = "The objective ledger identified surface or column phenomena during the period."
        event_source = "Atlas objective phenomena ledger"
    else:
        event_label = "Quiet objective-weather ledger"
        event_reading = "No configured phenomenon threshold was met during the reporting window."
        event_source = "Atlas objective phenomena ledger"

    if fronts.events:
        front = fronts.events[0]
        front_label = front.kind
        front_reading = front.briefing
        front_facts = [
            StoryFact("Candidates", str(len(fronts.events))),
            StoryFact("Confidence", f"{front.confidence:.0%}"),
            StoryFact("3 h temperature", _fmt(front.temperature_change_3h_c, "C", signed=True)),
        ]
    else:
        front_label = "No frontal-passage signature"
        front_reading = "The compound surface-change detector found no defensible frontal passage."
        front_facts = [
            StoryFact("Candidates", "0"),
            StoryFact("Requirement", "At least three compound signals"),
            StoryFact("Status", "No local passage marker"),
        ]

    if inversion_events:
        boundary_label = "Nocturnal low-level inversion"
        boundary_reading = "Model pressure levels identified stable nocturnal layers during the period."
    elif pbl_height is not None and pbl_height >= 2000:
        boundary_label = "Deep mixed boundary layer"
        boundary_reading = "The selected model profile indicates deep daytime turbulent mixing."
    elif pbl_height is not None and pbl_height <= 800:
        boundary_label = "Shallow boundary layer"
        boundary_reading = "The selected model profile indicates restricted vertical mixing."
    else:
        boundary_label = "Boundary-layer evolution"
        boundary_reading = "Model-derived mixing depth and parcel diagnostics describe the lower atmosphere."

    moisture_context = land.moisture_context or "Land-surface context unavailable"
    lower_moisture = moisture_context.lower()
    if "dry" in lower_moisture or "deficit" in lower_moisture:
        land_label = "Persistent land-surface deficit"
    elif "wet" in lower_moisture or "surplus" in lower_moisture:
        land_label = "Land-surface moisture surplus"
    else:
        land_label = "Near-normal water balance"

    nodes = [
        StoryNode(
            "regime",
            "synoptic",
            "Atmospheric setup",
            regime.label,
            regime.briefing,
            [
                StoryFact("Rule signals", ", ".join(regime.signals) or "No dominant signal"),
                StoryFact("Pressure", _fmt(current_metrics.get("pressure_mean_hpa"), "hPa")),
                StoryFact("Period", f"{len(regime.daily_labels)} local days"),
            ],
            "Atlas transparent regime rules",
            0.06,
            0.50,
        ),
        StoryNode(
            "sky",
            "observed",
            "Surface weather",
            _sky_label(cloud_rank, precipitation_total),
            "Cloud, precipitation and radiation together describe how the air mass expressed itself at the surface.",
            [
                StoryFact("Mean cloud", _fmt(current_metrics.get("cloud_cover_mean_pct"), "%")),
                StoryFact("Cloud rank", _rank(climate, "cloud_cover_mean_pct")),
                StoryFact("Precipitation", _fmt(precipitation_total, "mm")),
            ],
            "Open-Meteo surface fields and ERA5 climatology",
            0.45,
            0.10,
        ),
        StoryNode(
            "thermal",
            "observed",
            "Thermal character",
            _thermal_label(temperature_anomaly),
            "The period mean is compared with the standard-normal calendar window and the full record.",
            [
                StoryFact("Mean temperature", _fmt(current_metrics.get("temperature_mean_c"), "C")),
                StoryFact("Standard anomaly", _fmt(temperature_anomaly, "C", signed=True)),
                StoryFact("Full-record rank", _rank(climate, "temperature_mean_c")),
            ],
            "Open-Meteo surface analysis and 1991-2020 ERA5 normal",
            0.45,
            0.37,
        ),
        StoryNode(
            "events",
            "observed",
            "Observed phenomena",
            event_label,
            event_reading,
            [
                StoryFact("Ledger entries", str(len(phenomena.events))),
                StoryFact("Lightning", f"{len(lightning.frame):,} within {lightning_radius_km:.0f} km"),
                StoryFact("Radar maximum", _fmt(radar_max, "dBZ")),
            ],
            event_source,
            0.88,
            0.68,
        ),
        StoryNode(
            "front",
            "synoptic",
            "Passage diagnosis",
            front_label,
            front_reading,
            front_facts,
            "Atlas compound pressure, temperature, wind and precipitation detector",
            0.45,
            0.91,
        ),
        StoryNode(
            "pv",
            "impact",
            "Energy impact",
            _yield_label("PV", _finite(physical_energy.pv_capacity_factor_pct)),
            "Plane-of-array irradiance and cell-temperature derating translate the weather into reference PV output.",
            [
                StoryFact("Reference yield", _fmt(physical_energy.pv_yield_kwh_per_kwp, "kWh/kWp", 2)),
                StoryFact("Capacity factor", _fmt(physical_energy.pv_capacity_factor_pct, "%")),
                StoryFact("Radiation anomaly", _fmt(radiation.anomaly if radiation else None, "Wh/m2", 0, True)),
            ],
            "Atlas physically based fixed-array PV model",
            0.88,
            0.08,
        ),
        StoryNode(
            "land",
            "impact",
            "Land-surface impact",
            land_label,
            moisture_context,
            [
                StoryFact("7-day balance", _fmt(land.metrics.get("water_balance_7d_mm"), "mm", signed=True)),
                StoryFact("30-day balance", _fmt(land.metrics.get("water_balance_30d_mm"), "mm", signed=True)),
                StoryFact("Maximum VPD", _fmt(land.metrics.get("vpd_max_kpa"), "kPa")),
            ],
            "Open-Meteo land fields and FAO-56 reference evapotranspiration",
            0.88,
            0.34,
        ),
        StoryNode(
            "boundary",
            "observed",
            "Boundary layer",
            boundary_label,
            boundary_reading,
            [
                StoryFact("PBL height", _fmt(pbl_height, "m", 0)),
                StoryFact("SB CAPE", _fmt(cape, "J/kg", 0)),
                StoryFact("Inversion episodes", str(len(inversion_events))),
            ],
            "Open-Meteo historical-model pressure levels",
            0.45,
            0.64,
        ),
        StoryNode(
            "wind",
            "impact",
            "Energy impact",
            _yield_label("wind", _finite(physical_energy.wind_capacity_factor_pct)),
            "Density-corrected 100 m wind is translated through the generic reference-turbine power curve.",
            [
                StoryFact("Capacity factor", _fmt(physical_energy.wind_capacity_factor_pct, "%")),
                StoryFact("Full-load hours", _fmt(physical_energy.wind_full_load_hours, "h", 2)),
                StoryFact("Mean power density", _fmt(physical_energy.mean_wind_power_density_w_m2, "W/m2", 0)),
            ],
            "Atlas physically based reference-turbine model",
            0.88,
            0.94,
        ),
    ]

    edges = [
        StoryEdge("regime", "sky", "organized the cloud and precipitation pattern"),
        StoryEdge("regime", "thermal", "set the period-scale thermal character"),
        StoryEdge("regime", "boundary", "conditioned lower-atmosphere mixing"),
        StoryEdge("sky", "pv", "controlled the available irradiance"),
        StoryEdge("sky", "land", "altered rainfall and surface drying"),
        StoryEdge("thermal", "land", "modified atmospheric moisture demand"),
        StoryEdge("regime", "front", "provided the passage-scale background"),
        StoryEdge("front", "events", "was compared with the event chronology"),
        StoryEdge("front" if fronts.events else "regime", "wind", "organized the wind-energy environment"),
    ]
    if not fronts.events:
        edges.append(StoryEdge("regime", "events", "was checked against the objective event ledger"))

    return WeatherStory(
        title="Weather Story Graph",
        briefing=(
            "A deterministic chain from the large-scale regime through observed weather "
            "to land-surface and renewable-energy consequences."
        ),
        nodes=nodes,
        edges=edges,
    )
