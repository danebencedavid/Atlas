from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from atlas.config import AtlasConfig


MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Meteorological seasons. Winter spans a year boundary, so December is
# attributed to the following January/February in "season_year".
SEASON_MONTHS: dict[str, tuple[int, int, int]] = {
    "Winter": (12, 1, 2),
    "Spring": (3, 4, 5),
    "Summer": (6, 7, 8),
    "Autumn": (9, 10, 11),
}


@dataclass(frozen=True)
class RecordEntry:
    label: str
    value: float
    unit: str
    on_date: str
    metric: str


@dataclass(frozen=True)
class PeriodClimate:
    key: str
    name: str
    kind: str  # "month" or "season"
    years: int
    mean_temperature_c: float
    mean_precipitation_mm: float
    mean_wind_speed_ms: float
    mean_cloud_cover_pct: float
    mean_shortwave_wh_m2: float
    mean_water_balance_mm: float
    warmest_day: RecordEntry | None
    coldest_day: RecordEntry | None
    wettest_day: RecordEntry | None
    windiest_day: RecordEntry | None
    sunniest_day: RecordEntry | None
    driest_day: RecordEntry | None


@dataclass(frozen=True)
class Almanac:
    archive_start_year: int
    archive_end_year: int
    total_days: int
    months: list[PeriodClimate]
    seasons: list[PeriodClimate]
    all_time_records: list[RecordEntry]
    notes: list[str]


def _prepare_daily(archive: pd.DataFrame) -> pd.DataFrame:
    if archive.empty:
        return archive.copy()
    frame = archive.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    wind_column = (
        "wind_speed_100m_mean"
        if "wind_speed_100m_mean" in frame
        and pd.to_numeric(frame["wind_speed_100m_mean"], errors="coerce").notna().any()
        else "wind_speed_10m_mean"
    )
    et0 = (
        pd.to_numeric(frame["et0_fao_evapotranspiration_sum"], errors="coerce")
        if "et0_fao_evapotranspiration_sum" in frame
        else pd.Series(float("nan"), index=frame.index)
    )
    frame["temperature_c"] = pd.to_numeric(frame["temperature_2m_mean"], errors="coerce")
    frame["precipitation_mm"] = pd.to_numeric(frame["precipitation_sum"], errors="coerce")
    frame["wind_speed_ms"] = (
        pd.to_numeric(frame[wind_column], errors="coerce") if wind_column in frame else float("nan")
    )
    frame["cloud_cover_pct"] = pd.to_numeric(frame["cloud_cover_mean"], errors="coerce")
    frame["pressure_hpa"] = pd.to_numeric(frame["pressure_msl_mean"], errors="coerce")
    frame["shortwave_wh_m2"] = pd.to_numeric(frame["shortwave_radiation_sum"], errors="coerce") * 277.7777778
    frame["water_balance_mm"] = frame["precipitation_mm"] - et0
    frame["month"] = frame["date"].dt.month
    frame["year"] = frame["date"].dt.year
    frame["season_year"] = frame["year"] + (frame["month"] == 12).astype(int)
    return frame


def _extreme(frame: pd.DataFrame, column: str, label: str, unit: str, mode: str) -> RecordEntry | None:
    if column not in frame:
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    if series.empty:
        return None
    idx = series.idxmax() if mode == "max" else series.idxmin()
    row = frame.loc[idx]
    value = float(row[column])
    return RecordEntry(
        label=label,
        value=round(value, 1),
        unit=unit,
        on_date=pd.Timestamp(row["date"]).date().isoformat(),
        metric=column,
    )


def _period_climate(
    subset: pd.DataFrame,
    key: str,
    name: str,
    kind: str,
    group_column: str,
) -> PeriodClimate | None:
    if subset.empty:
        return None
    years = int(subset[group_column].nunique())
    grouped = subset.groupby(group_column)
    return PeriodClimate(
        key=key,
        name=name,
        kind=kind,
        years=years,
        mean_temperature_c=round(float(subset["temperature_c"].mean()), 1),
        mean_precipitation_mm=round(float(grouped["precipitation_mm"].sum().mean()), 1),
        mean_wind_speed_ms=round(float(subset["wind_speed_ms"].mean()), 1),
        mean_cloud_cover_pct=round(float(subset["cloud_cover_pct"].mean()), 1),
        mean_shortwave_wh_m2=round(float(grouped["shortwave_wh_m2"].sum().mean()), 0),
        mean_water_balance_mm=round(float(grouped["water_balance_mm"].sum().mean()), 1),
        warmest_day=_extreme(subset, "temperature_c", f"Warmest {name} day", "°C", "max"),
        coldest_day=_extreme(subset, "temperature_c", f"Coldest {name} day", "°C", "min"),
        wettest_day=_extreme(subset, "precipitation_mm", f"Wettest {name} day", "mm", "max"),
        windiest_day=_extreme(subset, "wind_speed_ms", f"Windiest {name} day", "m/s", "max"),
        sunniest_day=_extreme(subset, "shortwave_wh_m2", f"Sunniest {name} day", "Wh/m²", "max"),
        driest_day=_extreme(subset, "water_balance_mm", f"Driest {name} day", "mm", "min"),
    )


def _all_time_records(frame: pd.DataFrame, start_year: int) -> list[RecordEntry]:
    since = f"since {start_year}"
    candidates = [
        _extreme(frame, "temperature_c", f"Warmest day on record ({since})", "°C", "max"),
        _extreme(frame, "temperature_c", f"Coldest day on record ({since})", "°C", "min"),
        _extreme(frame, "precipitation_mm", f"Wettest day on record ({since})", "mm", "max"),
        _extreme(frame, "wind_speed_ms", f"Windiest day on record ({since})", "m/s", "max"),
        _extreme(frame, "shortwave_wh_m2", f"Sunniest day on record ({since})", "Wh/m²", "max"),
        _extreme(frame, "cloud_cover_pct", f"Cloudiest day on record ({since})", "%", "max"),
        _extreme(frame, "cloud_cover_pct", f"Clearest day on record ({since})", "%", "min"),
        _extreme(frame, "water_balance_mm", f"Driest day on record ({since})", "mm", "min"),
        _extreme(frame, "pressure_hpa", f"Highest pressure on record ({since})", "hPa", "max"),
        _extreme(frame, "pressure_hpa", f"Lowest pressure on record ({since})", "hPa", "min"),
    ]
    return [entry for entry in candidates if entry is not None]


def build_almanac(archive: pd.DataFrame, config: AtlasConfig) -> Almanac:
    """Build month, season and all-time climate summaries from the full daily ERA5 archive.

    ``archive`` is the same full-resolution daily frame produced by
    :func:`atlas.climatology.fetch_climate_archive`: one row per calendar day across every
    completed archive year, not the same-calendar-window samples used for anomaly percentiles.
    No additional network requests are made; this reuses data the pipeline already fetches.
    """
    if archive.empty:
        raise ValueError("Cannot build an almanac from an empty climate archive.")

    frame = _prepare_daily(archive)
    start_year = int(frame["year"].min())
    end_year = int(frame["year"].max())

    months = [
        climate
        for climate in (
            _period_climate(frame[frame["month"] == month], str(month), MONTH_NAMES[month - 1], "month", "year")
            for month in range(1, 13)
        )
        if climate is not None
    ]
    seasons = [
        climate
        for climate in (
            _period_climate(
                frame[frame["month"].isin(month_group)],
                name,
                name,
                "season",
                "season_year",
            )
            for name, month_group in SEASON_MONTHS.items()
        )
        if climate is not None
    ]
    records = _all_time_records(frame, start_year)

    notes = [
        (
            f"Month and season summaries and the record book use {len(frame)} daily ERA5 reanalysis "
            f"values for {config.location.name} from {start_year} to {end_year}."
        ),
        (
            "Daily temperature, wind and cloud cover are calendar-day means; precipitation and solar "
            "energy are calendar-day totals. Extremes reflect that same daily resolution, not sub-daily "
            "instantaneous readings."
        ),
        (
            "Winter groups December with the following January and February, so a winter is labelled "
            "by the year its January falls in."
        ),
    ]
    return Almanac(
        archive_start_year=start_year,
        archive_end_year=end_year,
        total_days=int(len(frame)),
        months=months,
        seasons=seasons,
        all_time_records=records,
        notes=notes,
    )
