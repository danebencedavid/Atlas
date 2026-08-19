from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ProjectConfig:
    name: str = "Atlas"
    tagline: str = "Rolling weather anomaly atlas and renewable energy situation report"
    # Absolute origin of the published site. Link shares (Facebook, X, WhatsApp) and
    # Open Graph tags need a canonical URL; relative paths are useless off-site.
    site_url: str = "https://danebencedavid.github.io/Atlas"


@dataclass(frozen=True)
class LocationConfig:
    name: str = "Debrecen"
    region: str = "Hungary"
    station_note: str = "Debrecen only; no multi-city or Hungary-wide expansion is planned"
    latitude: float = 47.5316
    longitude: float = 21.6273
    timezone: str = "Europe/Budapest"


@dataclass(frozen=True)
class BaselineConfig:
    years: int = 10
    minimum_years: int = 5


@dataclass(frozen=True)
class ClimatologyConfig:
    standard_start_year: int = 1991
    standard_end_year: int = 2020
    archive_start_year: int = 1990
    minimum_standard_years: int = 24


@dataclass(frozen=True)
class LandSurfaceConfig:
    enabled: bool = True
    context_days: int = 90
    required: bool = False


@dataclass(frozen=True)
class ReportingConfig:
    window_days: int = 3
    context_days: int = 7
    schedule_days: int = 3


@dataclass(frozen=True)
class ElectricityConfig:
    enabled: bool = True
    provider: str = "energy_charts"
    country: str = "hu"
    bidding_zone: str = "HU"
    required: bool = False


@dataclass(frozen=True)
class ProfileConfig:
    enabled: bool = True
    pressure_levels_hpa: list[int] = field(
        default_factory=lambda: [1000, 950, 925, 850, 800, 700, 600, 500, 400, 300, 250, 200]
    )
    target_hour_utc: int = 12
    required: bool = False


@dataclass(frozen=True)
class HungaroMetConfig:
    enabled: bool = True
    station_id: int = 64711
    station_name: str = "Debrecen Airport"
    radar_radius_km: float = 140.0
    radar_replay_interval_minutes: int = 60
    radar_accumulation_interval_minutes: int = 30
    radar_display_stride: int = 3
    lightning_radius_km: float = 150.0
    required: bool = False


@dataclass(frozen=True)
class SatelliteConfig:
    enabled: bool = True
    products: list[str] = field(
        default_factory=lambda: [
            "AirmassRGB",
            "NaturalRGB",
            "NightRGB",
            "FogRGB",
            "InfraCloud",
        ]
    )
    frame_interval_minutes: int = 180
    image_width_px: int = 960
    webp_quality: int = 72
    required: bool = False


@dataclass(frozen=True)
class AnalogConfig:
    enabled: bool = True
    years: int = 15
    season_window_days: int = 45
    count: int = 5


@dataclass(frozen=True)
class SynopticConfig:
    enabled: bool = True
    latitude_min: float = 44.0
    latitude_max: float = 51.0
    longitude_min: float = 16.0
    longitude_max: float = 26.0
    grid_step_degrees: float = 1.0
    frame_interval_hours: int = 6
    required: bool = False


@dataclass(frozen=True)
class TrajectoryConfig:
    """Back-trajectory settings.

    The synoptic grid is far too small to trace an air mass: at 850 hPa a parcel
    crosses its 700 km width in roughly twelve hours. This uses its own wider and
    coarser domain, carrying only the fields the integration needs.
    """

    enabled: bool = True
    level_hpa: int = 850
    hours: int = 72
    latitude_min: float = 34.0
    latitude_max: float = 62.0
    longitude_min: float = -10.0
    longitude_max: float = 40.0
    grid_step_degrees: float = 3.0
    required: bool = False


@dataclass(frozen=True)
class ForecastArchiveConfig:
    """Forecast verification archive settings.

    Training data comes from the Previous Runs API, where a value suffixed
    ``_previous_dayN`` was predicted N*24 hours before its valid time. The
    Historical Forecast API is deliberately excluded: it stitches together the
    earliest hours of successive runs, so a model trained on it would learn from
    information unavailable at live inference time.

    ``start_date`` is the probed beginning of the archive, not a preference. Runs
    before roughly 2024-01-20 return null for every variable.
    """

    enabled: bool = True
    start_date: str = "2024-01-22"
    lead_days: list[int] = field(default_factory=lambda: [1, 2, 3])
    models: list[str] = field(
        default_factory=lambda: ["best_match", "ecmwf_ifs025", "icon_seamless"]
    )
    variables: list[str] = field(
        default_factory=lambda: [
            "temperature_2m",
            "shortwave_radiation",
            "direct_radiation",
            "diffuse_radiation",
            "wind_speed_10m",
            "wind_gusts_10m",
            "cloud_cover",
            "relative_humidity_2m",
        ]
    )
    # Two-week windows with at most ten variables keep each request near one
    # weighted API call.
    chunk_days: int = 14
    max_variables_per_request: int = 10
    request_delay_seconds: float = 1.2
    # Committed rather than left under the ignored data/ tree, because the live
    # collector is append-only and must survive between CI runs.
    archive_dir: Path = Path("data/forecast_archive")


@dataclass(frozen=True)
class PhysicalEnergyConfig:
    pv_tilt_degrees: float = 35.0
    pv_azimuth_degrees: float = 180.0
    pv_temperature_coefficient: float = -0.004
    wind_hub_height_m: float = 100.0
    wind_cut_in_ms: float = 3.0
    wind_rated_ms: float = 12.0
    wind_cut_out_ms: float = 25.0


@dataclass(frozen=True)
class OutputConfig:
    data_dir: Path = Path("data")
    reports_dir: Path = Path("reports")
    site_dir: Path = Path("site")


@dataclass(frozen=True)
class OperationsConfig:
    max_period_lag_days: int = 7
    minimum_hourly_coverage: float = 0.95
    # Observational inputs carry their own thresholds. Without these the gridded
    # frame was the only gated input, which let editions publish with the headline
    # day almost entirely unobserved.
    minimum_station_coverage: float = 0.95
    minimum_radar_coverage: float = 0.90
    # The composite archive retains roughly this much against a 72-hour window, so
    # the radar threshold applies to what is reachable rather than to the window.
    radar_retention_hours: float = 71.0
    # How far the newest observation may fall short of the window end before the
    # build refuses to publish.
    maximum_observation_shortfall_hours: float = 2.0


@dataclass(frozen=True)
class AtlasConfig:
    project: ProjectConfig = field(default_factory=ProjectConfig)
    location: LocationConfig = field(default_factory=LocationConfig)
    baseline: BaselineConfig = field(default_factory=BaselineConfig)
    climatology: ClimatologyConfig = field(default_factory=ClimatologyConfig)
    land_surface: LandSurfaceConfig = field(default_factory=LandSurfaceConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    operations: OperationsConfig = field(default_factory=OperationsConfig)
    electricity: ElectricityConfig = field(default_factory=ElectricityConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    hungaromet: HungaroMetConfig = field(default_factory=HungaroMetConfig)
    satellite: SatelliteConfig = field(default_factory=SatelliteConfig)
    analogs: AnalogConfig = field(default_factory=AnalogConfig)
    synoptic: SynopticConfig = field(default_factory=SynopticConfig)
    trajectory: TrajectoryConfig = field(default_factory=TrajectoryConfig)
    forecast_archive: ForecastArchiveConfig = field(default_factory=ForecastArchiveConfig)
    physical_energy: PhysicalEnergyConfig = field(default_factory=PhysicalEnergyConfig)
    outputs: OutputConfig = field(default_factory=OutputConfig)


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Config section '{key}' must be a mapping.")
    return value


def _forecast_archive_config(raw: dict[str, Any]) -> ForecastArchiveConfig:
    settings = dict(raw)
    if "archive_dir" in settings:
        settings["archive_dir"] = Path(settings["archive_dir"])
    return ForecastArchiveConfig(**settings)


def load_config(path: str | Path = "configs/atlas.yml") -> AtlasConfig:
    config_path = Path(path)
    raw: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

    outputs = _section(raw, "outputs")
    return AtlasConfig(
        project=ProjectConfig(**_section(raw, "project")),
        location=LocationConfig(**_section(raw, "location")),
        baseline=BaselineConfig(**_section(raw, "baseline")),
        climatology=ClimatologyConfig(**_section(raw, "climatology")),
        land_surface=LandSurfaceConfig(**_section(raw, "land_surface")),
        reporting=ReportingConfig(**_section(raw, "reporting")),
        operations=OperationsConfig(**_section(raw, "operations")),
        electricity=ElectricityConfig(**_section(raw, "electricity")),
        profile=ProfileConfig(**_section(raw, "profile")),
        hungaromet=HungaroMetConfig(**_section(raw, "hungaromet")),
        satellite=SatelliteConfig(**_section(raw, "satellite")),
        analogs=AnalogConfig(**_section(raw, "analogs")),
        synoptic=SynopticConfig(**_section(raw, "synoptic")),
        trajectory=TrajectoryConfig(**_section(raw, "trajectory")),
        forecast_archive=_forecast_archive_config(_section(raw, "forecast_archive")),
        physical_energy=PhysicalEnergyConfig(**_section(raw, "physical_energy")),
        outputs=OutputConfig(
            data_dir=Path(outputs.get("data_dir", "data")),
            reports_dir=Path(outputs.get("reports_dir", "reports")),
            site_dir=Path(outputs.get("site_dir", "site")),
        ),
    )
