from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ProjectConfig:
    name: str = "Atlas"
    tagline: str = "Rolling weather anomaly atlas and renewable energy situation report"


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
        default_factory=lambda: [1000, 925, 850, 700, 500, 400, 300, 250, 200]
    )
    target_hour_utc: int = 12
    required: bool = False


@dataclass(frozen=True)
class OutputConfig:
    data_dir: Path = Path("data")
    reports_dir: Path = Path("reports")
    site_dir: Path = Path("site")


@dataclass(frozen=True)
class OperationsConfig:
    max_period_lag_days: int = 7
    minimum_hourly_coverage: float = 0.95


@dataclass(frozen=True)
class AtlasConfig:
    project: ProjectConfig = field(default_factory=ProjectConfig)
    location: LocationConfig = field(default_factory=LocationConfig)
    baseline: BaselineConfig = field(default_factory=BaselineConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    operations: OperationsConfig = field(default_factory=OperationsConfig)
    electricity: ElectricityConfig = field(default_factory=ElectricityConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    outputs: OutputConfig = field(default_factory=OutputConfig)


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Config section '{key}' must be a mapping.")
    return value


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
        reporting=ReportingConfig(**_section(raw, "reporting")),
        operations=OperationsConfig(**_section(raw, "operations")),
        electricity=ElectricityConfig(**_section(raw, "electricity")),
        profile=ProfileConfig(**_section(raw, "profile")),
        outputs=OutputConfig(
            data_dir=Path(outputs.get("data_dir", "data")),
            reports_dir=Path(outputs.get("reports_dir", "reports")),
            site_dir=Path(outputs.get("site_dir", "site")),
        ),
    )
