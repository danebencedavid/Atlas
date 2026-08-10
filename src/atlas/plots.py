from __future__ import annotations

from datetime import date
from pathlib import Path
import json

import numpy as np
import pandas as pd
import plotly.figure_factory as ff
import plotly.graph_objects as go
from PIL import Image
from pvlib.location import Location
from plotly.subplots import make_subplots

from atlas.anomalies import Anomaly
from atlas.climatology import ClimateReference
from atlas.config import AtlasConfig
from atlas.electricity import ElectricitySummary
from atlas.energy import PhysicalEnergy
from atlas.fronts import FrontAnalysis
from atlas.hungaromet import LightningArchive, RadarArchive, StationObservations, station_hourly
from atlas.land import LandSurfaceAnalysis, SOIL_MOISTURE_COLUMNS, SOIL_TEMPERATURE_COLUMNS
from atlas.phenomena import PhenomenaAnalysis
from atlas.profile import ModelProfile
from atlas.regimes import RegimeClassification
from atlas.satellite import SatelliteArchive
from atlas.synoptic import SynopticArchive


PLOT_CONFIG = {
    "displaylogo": False,
    "scrollZoom": True,
    "responsive": True,
    "modeBarButtonsToAdd": ["drawline", "drawrect", "eraseshape"],
}


def _prepare(frame: pd.DataFrame, timezone_name: str) -> pd.DataFrame:
    prepared = frame.copy()
    prepared["local_time"] = pd.to_datetime(prepared["time"], utc=True).dt.tz_convert(timezone_name)
    return prepared


def _save(fig: go.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    layout_updates = {
        "template": "plotly_white",
        "font": {"family": "Inter, Segoe UI, Arial, sans-serif", "color": "#172033"},
        "margin": {"l": 58, "r": 26, "t": 64, "b": 48},
        "dragmode": "zoom",
    }
    if fig.layout.hovermode is None:
        layout_updates["hovermode"] = "x unified"

    # Dropdowns and play controls sit above the plotting area, where a 64px top
    # margin puts them on top of the title. Give those figures room for both and
    # stack them: title against the top of the container, controls beneath it.
    menus = tuple(fig.layout.updatemenus or ())
    if menus:
        layout_updates["margin"] = {"l": 58, "r": 26, "t": 116, "b": 48}
        # Positioned key by key: passing a whole title dict would drop the text that
        # each figure sets for itself.
        layout_updates["title_yref"] = "container"
        layout_updates["title_y"] = 0.97
        layout_updates["title_yanchor"] = "top"
        fig.update_layout(
            updatemenus=[
                {**menu.to_plotly_json(), "y": 1.04, "yanchor": "bottom"} for menu in menus
            ]
        )
    fig.update_layout(**layout_updates)
    fig.write_html(path, include_plotlyjs="cdn", full_html=True, config=PLOT_CONFIG)
    return path


def _empty_figure(title: str, message: str, output: Path, height: int = 520) -> Path:
    fig = go.Figure()
    fig.add_annotation(
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        text=message,
        showarrow=False,
        font={"size": 16, "color": "#667085"},
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(title=title, height=height)
    return _save(fig, output)


def plot_meteogram(
    frame: pd.DataFrame,
    output: Path,
    config: AtlasConfig,
    fronts: FrontAnalysis | None = None,
    title: str = "Rolling 72-Hour Interactive Meteogram",
) -> Path:
    local = _prepare(frame, config.location.timezone)
    x = local["local_time"]
    fig = make_subplots(
        rows=5,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        subplot_titles=("Temperature", "Sea-Level Pressure", "Wind", "Precipitation", "Cloud And Solar"),
    )
    fig.add_trace(go.Scatter(x=x, y=local["temperature_2m"], name="Temperature", line={"color": "#c43c39"}), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=local["dew_point_2m"], name="Dew point", line={"color": "#2077b4"}), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=local["pressure_msl"], name="Pressure", line={"color": "#3f3f46"}), row=2, col=1)
    fig.add_trace(go.Scatter(x=x, y=local["wind_speed_10m"], name="10 m wind", line={"color": "#2f7d62"}), row=3, col=1)
    if "wind_speed_100m" in local:
        fig.add_trace(go.Scatter(x=x, y=local["wind_speed_100m"], name="100 m wind", line={"color": "#58a788"}), row=3, col=1)
    fig.add_trace(go.Scatter(x=x, y=local["wind_gusts_10m"], name="Gusts", line={"color": "#111827", "dash": "dot"}), row=3, col=1)
    fig.add_trace(go.Bar(x=x, y=local["precipitation"], name="Precipitation", marker={"color": "#2f6fbb"}), row=4, col=1)
    fig.add_trace(go.Scatter(x=x, y=local["cloud_cover"], name="Cloud cover", fill="tozeroy", line={"color": "#94a3b8"}), row=5, col=1)
    fig.add_trace(go.Scatter(x=x, y=local["shortwave_radiation"], name="Shortwave radiation", line={"color": "#d99100"}), row=5, col=1)
    fig.update_yaxes(title_text="deg C", row=1, col=1)
    fig.update_yaxes(title_text="hPa", row=2, col=1)
    fig.update_yaxes(title_text="m/s", row=3, col=1)
    fig.update_yaxes(title_text="mm/h", row=4, col=1)
    fig.update_yaxes(title_text="% / W m-2", row=5, col=1)
    for event in fronts.events if fronts is not None else []:
        timestamp = event.time.tz_convert(config.location.timezone)
        fig.add_vline(x=timestamp, line_color="#b42318", line_dash="dash", line_width=1.5)
        fig.add_annotation(
            x=timestamp,
            y=1.01,
            xref="x5",
            yref="paper",
            text=event.kind.replace("Probable ", ""),
            showarrow=False,
            textangle=-90,
            font={"size": 10, "color": "#b42318"},
        )
    fig.update_layout(title=title, height=980)
    return _save(fig, output)


def plot_seven_day_context(
    frame: pd.DataFrame,
    current_start: date,
    output: Path,
    config: AtlasConfig,
) -> Path:
    local = _prepare(frame, config.location.timezone)
    local["date"] = local["local_time"].dt.date
    daily = (
        local.groupby("date")
        .agg(
            temperature_min_c=("temperature_2m", "min"),
            temperature_max_c=("temperature_2m", "max"),
            precipitation_mm=("precipitation", "sum"),
            shortwave_wh_m2=("shortwave_radiation", "sum"),
            wind_mean_ms=("wind_speed_100m", "mean"),
        )
        .reset_index()
    )
    x = pd.to_datetime(daily["date"])
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.09,
        specs=[[{}], [{}], [{"secondary_y": True}]],
        subplot_titles=("Daily Temperature Range", "Daily Precipitation", "Solar And Wind Context"),
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=daily["temperature_max_c"],
            name="Daily maximum",
            line={"color": "#c43c39"},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=daily["temperature_min_c"],
            name="Daily minimum",
            fill="tonexty",
            fillcolor="rgba(37, 99, 235, 0.10)",
            line={"color": "#2563eb"},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(x=x, y=daily["precipitation_mm"], name="Precipitation", marker={"color": "#2563eb"}),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=x,
            y=daily["shortwave_wh_m2"],
            name="Solar radiation",
            marker={"color": "#e0a11b"},
        ),
        row=3,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=daily["wind_mean_ms"],
            name="100 m wind",
            mode="lines+markers",
            line={"color": "#047857", "width": 3},
        ),
        row=3,
        col=1,
        secondary_y=True,
    )
    highlight_start = pd.Timestamp(current_start)
    highlight_end = pd.Timestamp(daily["date"].max()) + pd.Timedelta(days=1)
    for row in range(1, 4):
        fig.add_vrect(
            x0=highlight_start,
            x1=highlight_end,
            fillcolor="#fef3c7",
            opacity=0.28,
            line_width=0,
            row=row,
            col=1,
        )
    fig.update_yaxes(title_text="deg C", row=1, col=1)
    fig.update_yaxes(title_text="mm", row=2, col=1)
    fig.update_yaxes(title_text="Wh/m2", row=3, col=1, secondary_y=False)
    fig.update_yaxes(title_text="m/s", row=3, col=1, secondary_y=True)
    fig.update_layout(title="Seven-Day Weather Context - Highlighted Area Is The Current Report", height=720)
    return _save(fig, output)


def plot_wind_rose(frame: pd.DataFrame, output: Path, config: AtlasConfig) -> Path:
    local = _prepare(frame, config.location.timezone)
    direction = pd.to_numeric(local["wind_direction_10m"], errors="coerce").dropna()
    speed = pd.to_numeric(local.loc[direction.index, "wind_speed_10m"], errors="coerce")
    bins = [0, 2, 4, 6, 8, np.inf]
    labels = ["0-2", "2-4", "4-6", "6-8", "8+"]
    sector_labels = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    sector_ids = (np.floor(((direction + 11.25) % 360) / 22.5).astype(int)) % 16
    speed_bins = pd.cut(speed, bins=bins, labels=labels, right=False)
    colors = ["#dbeafe", "#93c5fd", "#38bdf8", "#0f766e", "#134e4a"]

    fig = go.Figure()
    for label, color in zip(labels, colors):
        counts = np.array([(speed_bins[(sector_ids == idx)] == label).sum() for idx in range(16)])
        percent = counts / max(len(direction), 1) * 100
        fig.add_trace(
            go.Barpolar(
                r=percent,
                theta=sector_labels,
                name=f"{label} m/s",
                marker_color=color,
                marker_line_color="white",
                marker_line_width=1,
                hovertemplate="%{theta}<br>%{r:.1f}%<extra>" + f"{label} m/s</extra>",
            )
        )
    fig.update_layout(
        title="Interactive Wind Rose",
        height=680,
        polar={
            "barmode": "stack",
            "angularaxis": {"direction": "clockwise", "rotation": 90},
            "radialaxis": {"ticksuffix": "%"},
        },
    )
    return _save(fig, output)


def plot_pressure_tendency(frame: pd.DataFrame, output: Path, config: AtlasConfig) -> Path:
    local = _prepare(frame, config.location.timezone)
    local["tendency_6h"] = local["pressure_msl"].diff(6)
    x = local["local_time"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, subplot_titles=("Sea-Level Pressure", "6h Tendency"))
    fig.add_trace(go.Scatter(x=x, y=local["pressure_msl"], name="Pressure", line={"color": "#27272a"}), row=1, col=1)
    colors = np.where(local["tendency_6h"] >= 0, "#2563eb", "#dc2626")
    fig.add_trace(go.Bar(x=x, y=local["tendency_6h"], name="6h tendency", marker={"color": colors}), row=2, col=1)
    sharp = local[local["tendency_6h"].abs() >= 4]
    fig.add_trace(go.Scatter(x=sharp["local_time"], y=sharp["tendency_6h"], mode="markers", name="sharp tendency", marker={"color": "#111827", "size": 8}), row=2, col=1)
    fig.add_hline(y=0, line_color="#71717a", row=2, col=1)
    fig.update_yaxes(title_text="hPa", row=1, col=1)
    fig.update_yaxes(title_text="hPa / 6h", row=2, col=1)
    fig.update_layout(title="Interactive Pressure Tendency", height=620)
    return _save(fig, output)


def _humid_periods(local: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    mask = (local["temperature_2m"] - local["dew_point_2m"]) <= 2.0
    periods: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    start: pd.Timestamp | None = None
    previous: pd.Timestamp | None = None
    for timestamp, humid in zip(local["local_time"], mask):
        if humid and start is None:
            start = timestamp
        if not humid and start is not None and previous is not None:
            periods.append((start, previous))
            start = None
        previous = timestamp
    if start is not None and previous is not None:
        periods.append((start, previous))
    return periods


def plot_dewpoint_spread(frame: pd.DataFrame, output: Path, config: AtlasConfig) -> Path:
    local = _prepare(frame, config.location.timezone)
    local["spread"] = local["temperature_2m"] - local["dew_point_2m"]
    x = local["local_time"]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=x, y=local["temperature_2m"], name="Temperature", line={"color": "#b91c1c"}), secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=local["dew_point_2m"], name="Dew point", line={"color": "#1d4ed8"}), secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=local["spread"], name="Spread", line={"color": "#0f766e", "dash": "dot"}), secondary_y=True)
    for start, end in _humid_periods(local):
        fig.add_vrect(x0=start, x1=end, fillcolor="#bae6fd", opacity=0.35, line_width=0)
    fig.update_yaxes(title_text="deg C", secondary_y=False)
    fig.update_yaxes(title_text="spread deg C", secondary_y=True)
    fig.update_layout(title="Interactive Temperature-Dew Point Spread", height=560)
    return _save(fig, output)


def plot_solar_diurnal(
    frame: pd.DataFrame,
    climate: ClimateReference,
    output: Path,
    config: AtlasConfig,
) -> Path:
    current = _prepare(frame, config.location.timezone)
    current["date"] = current["local_time"].dt.date
    current["hour"] = current["local_time"].dt.hour + current["local_time"].dt.minute / 60
    representative_date = pd.Timestamp(sorted(current["date"].unique())[len(current["date"].unique()) // 2])
    representative_times = pd.date_range(
        representative_date,
        periods=24,
        freq="h",
        tz=config.location.timezone,
    )
    clear_sky = Location(
        config.location.latitude,
        config.location.longitude,
        tz=config.location.timezone,
    ).get_clearsky(representative_times)["ghi"]
    standard_daily_total = float(
        pd.to_numeric(
            climate.standard_table["shortwave_total_wh_m2"], errors="coerce"
        ).median()
        / max(len(current["date"].unique()), 1)
    )
    typical = clear_sky * standard_daily_total / max(float(clear_sky.sum()), 1.0)

    fig = go.Figure()
    for day, group in current.groupby("date"):
        fig.add_trace(go.Scatter(x=group["hour"], y=group["shortwave_radiation"], mode="lines", name=str(day), opacity=0.7))
    fig.add_trace(go.Scatter(x=representative_times.hour, y=typical.values, mode="lines", name="1991-2020 energy-scaled clear-sky shape", line={"color": "#111827", "width": 4, "dash": "dash"}))
    fig.update_layout(title="Interactive Solar Radiation Diurnal Curves", height=560, xaxis_title="Local hour", yaxis_title="W m-2")
    fig.update_xaxes(range=[0, 23], dtick=3)
    return _save(fig, output)


def plot_anomaly_bars(anomalies: list[Anomaly], output: Path) -> Path:
    labels = [item.label for item in anomalies]
    z_scores = [item.z_score for item in anomalies]
    hover = [
        f"{item.label}<br>This period: {item.value:.1f} {item.unit}<br>Baseline: {item.baseline_mean:.1f} {item.unit}<br>Anomaly: {item.anomaly:+.1f} {item.unit}<br>Percentile: {item.percentile:.0f}"
        for item in anomalies
    ]
    colors = ["#dc2626" if value > 0 else "#2563eb" for value in z_scores]
    fig = go.Figure(go.Bar(x=labels, y=z_scores, marker={"color": colors}, text=[f"{value:+.1f}" for value in z_scores], hovertext=hover, hoverinfo="text"))
    fig.add_hline(y=0, line_color="#71717a")
    fig.update_layout(title="Interactive 3-Day Anomalies Versus Baseline", height=560, yaxis_title="standard deviations from normal")
    return _save(fig, output)


def plot_regime_strip(
    frame: pd.DataFrame,
    regime: RegimeClassification,
    output: Path,
    config: AtlasConfig,
) -> Path:
    colors = {
        "sunny": "#facc15",
        "stagnant": "#94a3b8",
        "frontal": "#38bdf8",
        "hot": "#ef4444",
        "frost": "#93c5fd",
        "mixed": "#a7f3d0",
    }
    local = _prepare(frame, config.location.timezone)
    labels = [pd.Timestamp(day).strftime("%a %d %b") for day in sorted(local["local_time"].dt.date.unique())]
    values = regime.daily_labels[: len(labels)]
    while len(values) < len(labels):
        values.append("mixed")
    fig = go.Figure()
    for idx, value in enumerate(values):
        fig.add_trace(
            go.Bar(
                x=[labels[idx]],
                y=[1],
                marker={"color": colors.get(value, "#e5e7eb")},
                text=[value],
                textposition="inside",
                name=value,
                hovertemplate=f"{labels[idx]}<br>{value}<extra></extra>",
                showlegend=False,
            )
        )
    fig.update_layout(title="Interactive Daily Regime Strip", height=260, yaxis={"visible": False}, xaxis_title="", bargap=0.06)
    return _save(fig, output)


def _hourly_electricity_weather(
    weather: pd.DataFrame,
    electricity: pd.DataFrame,
) -> pd.DataFrame:
    weather_hourly = weather.copy()
    weather_hourly["time"] = pd.to_datetime(weather_hourly["time"], utc=True).dt.floor("h")
    weather_hourly = weather_hourly.groupby("time").mean(numeric_only=True).reset_index()
    electricity_hourly = electricity.copy()
    electricity_hourly["time"] = pd.to_datetime(electricity_hourly["time"], utc=True).dt.floor("h")
    electricity_hourly = electricity_hourly.groupby("time").mean(numeric_only=True).reset_index()
    return weather_hourly.merge(electricity_hourly, on="time", how="inner")


def plot_electricity_overview(
    electricity: pd.DataFrame,
    output: Path,
    config: AtlasConfig,
) -> Path:
    if electricity.empty:
        return _empty_figure(
            "Hungary Electricity System",
            "Electricity data was unavailable for this reporting period.",
            output,
            700,
        )
    local = electricity.copy()
    local["local_time"] = pd.to_datetime(local["time"], utc=True).dt.tz_convert(config.location.timezone)
    x = local["local_time"]
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=("System Load", "Variable Renewable Generation", "Day-Ahead Price"),
    )
    if "load_mw" in local:
        fig.add_trace(
            go.Scatter(x=x, y=local["load_mw"], name="Load", line={"color": "#172033", "width": 2.5}),
            row=1,
            col=1,
        )
    if "residual_load_mw" in local:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=local["residual_load_mw"],
                name="Residual load",
                line={"color": "#c2410c", "dash": "dot"},
            ),
            row=1,
            col=1,
        )
    renewable_columns = [
        ("solar_generation_mw", "Solar generation", "#e0a11b"),
        ("wind_onshore_generation_mw", "Onshore wind", "#047857"),
        ("wind_offshore_generation_mw", "Offshore wind", "#0f766e"),
    ]
    for column, label, color in renewable_columns:
        if column in local:
            fig.add_trace(
                go.Scatter(x=x, y=local[column], name=label, line={"color": color}, fill="tozeroy"),
                row=2,
                col=1,
            )
    if "day_ahead_price_eur_mwh" in local:
        price_colors = np.where(local["day_ahead_price_eur_mwh"] < 0, "#2563eb", "#8b5cf6")
        fig.add_trace(
            go.Bar(
                x=x,
                y=local["day_ahead_price_eur_mwh"],
                name="Day-ahead price",
                marker={"color": price_colors},
            ),
            row=3,
            col=1,
        )
    fig.update_yaxes(title_text="MW", row=1, col=1)
    fig.update_yaxes(title_text="MW", row=2, col=1)
    fig.update_yaxes(title_text="EUR/MWh", row=3, col=1)
    fig.update_layout(title="Hungary Electricity System - Rolling 72-Hour Context", height=820)
    return _save(fig, output)


def _add_scatter_with_trend(
    fig: go.Figure,
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    x_label: str,
    y_label: str,
    row: int,
    color: str,
) -> None:
    usable = frame[[x_column, y_column, "time"]].dropna()
    if usable.empty:
        return
    local_time = pd.to_datetime(usable["time"], utc=True).dt.strftime("%Y-%m-%d %H:%M UTC")
    fig.add_trace(
        go.Scatter(
            x=usable[x_column],
            y=usable[y_column],
            mode="markers",
            name=y_label,
            marker={"color": color, "size": 9, "opacity": 0.68},
            customdata=local_time,
            hovertemplate=f"{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<br>%{{customdata}}<extra></extra>",
        ),
        row=row,
        col=1,
    )
    if len(usable) >= 3 and usable[x_column].nunique() > 1:
        slope, intercept = np.polyfit(usable[x_column], usable[y_column], 1)
        trend_x = np.linspace(float(usable[x_column].min()), float(usable[x_column].max()), 50)
        fig.add_trace(
            go.Scatter(
                x=trend_x,
                y=slope * trend_x + intercept,
                mode="lines",
                name=f"{y_label} trend",
                line={"color": "#172033", "dash": "dash"},
                hoverinfo="skip",
            ),
            row=row,
            col=1,
        )
    fig.update_xaxes(title_text=x_label, row=row, col=1)
    fig.update_yaxes(title_text=y_label, row=row, col=1)


def plot_weather_electricity_links(
    weather: pd.DataFrame,
    electricity: pd.DataFrame,
    output: Path,
) -> Path:
    if electricity.empty:
        return _empty_figure(
            "Weather-Electricity Relationships",
            "Electricity data was unavailable for weather comparison.",
            output,
            720,
        )
    aligned = _hourly_electricity_weather(weather, electricity)
    wind_generation_columns = [
        column
        for column in ["wind_onshore_generation_mw", "wind_offshore_generation_mw"]
        if column in aligned
    ]
    if wind_generation_columns:
        aligned["wind_generation_mw"] = aligned[wind_generation_columns].sum(axis=1, min_count=1)
    fig = make_subplots(
        rows=2,
        cols=1,
        vertical_spacing=0.16,
        subplot_titles=(
            "Debrecen Solar Radiation Versus Hungary Solar Generation",
            "Debrecen 100 m Wind Versus Hungary Wind Generation",
        ),
    )
    if "solar_generation_mw" in aligned:
        _add_scatter_with_trend(
            fig,
            aligned,
            "shortwave_radiation",
            "solar_generation_mw",
            "Debrecen radiation (W/m2)",
            "Hungary solar (MW)",
            1,
            "#e0a11b",
        )
    if "wind_generation_mw" in aligned:
        wind_column = "wind_speed_100m" if "wind_speed_100m" in aligned else "wind_speed_10m"
        _add_scatter_with_trend(
            fig,
            aligned,
            wind_column,
            "wind_generation_mw",
            "Debrecen wind (m/s)",
            "Hungary wind (MW)",
            2,
            "#047857",
        )
    if not fig.data:
        return _empty_figure(
            "Weather-Electricity Relationships",
            "Matching solar or wind generation series were not available.",
            output,
            720,
        )
    fig.update_layout(title="Local Weather And National Electricity - Diagnostic Relationship", height=780)
    return _save(fig, output)


def _skew_x(temperature_c: np.ndarray | pd.Series, pressure_hpa: np.ndarray | pd.Series) -> np.ndarray:
    return np.asarray(temperature_c, dtype=float) + 35.0 * np.log(1000.0 / np.asarray(pressure_hpa, dtype=float))


def plot_model_profile(profile: ModelProfile, output: Path) -> Path:
    if profile.frame.empty:
        return _empty_figure(
            "Interactive Skew-T Model Profile",
            "Pressure-level model data was unavailable for this reporting period.",
            output,
            760,
        )
    frame = profile.frame.sort_values("pressure_hpa", ascending=False)
    pressure = frame["pressure_hpa"].to_numpy(dtype=float)
    fig = make_subplots(
        rows=1,
        cols=2,
        shared_yaxes=True,
        column_widths=[0.76, 0.24],
        horizontal_spacing=0.08,
        subplot_titles=("Skew-T Thermodynamic Profile", "Wind Profile"),
    )
    grid_pressure = np.geomspace(max(pressure), min(pressure), 70)
    for isotherm in range(-80, 51, 10):
        fig.add_trace(
            go.Scatter(
                x=_skew_x(np.full_like(grid_pressure, isotherm), grid_pressure),
                y=grid_pressure,
                mode="lines",
                line={"color": "#d9e0ea", "width": 1},
                hoverinfo="skip",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
    for theta in range(270, 421, 20):
        temperature = theta * (grid_pressure / 1000.0) ** 0.286 - 273.15
        fig.add_trace(
            go.Scatter(
                x=_skew_x(temperature, grid_pressure),
                y=grid_pressure,
                mode="lines",
                line={"color": "#ead8b0", "width": 1, "dash": "dot"},
                hoverinfo="skip",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
    custom = np.column_stack(
        [
            frame["temperature_c"],
            frame["dew_point_c"],
            frame["relative_humidity_pct"],
            frame["geopotential_height_m"],
        ]
    )
    fig.add_trace(
        go.Scatter(
            x=_skew_x(frame["temperature_c"], pressure),
            y=pressure,
            mode="lines+markers",
            name="Temperature",
            line={"color": "#dc2626", "width": 3},
            customdata=custom,
            hovertemplate=(
                "Pressure %{y:.0f} hPa<br>Temperature %{customdata[0]:.1f} deg C"
                "<br>RH %{customdata[2]:.0f}%<br>Height %{customdata[3]:.0f} m<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=_skew_x(frame["dew_point_c"], pressure),
            y=pressure,
            mode="lines+markers",
            name="Dew point",
            line={"color": "#2563eb", "width": 3},
            customdata=custom,
            hovertemplate=(
                "Pressure %{y:.0f} hPa<br>Dew point %{customdata[1]:.1f} deg C"
                "<br>RH %{customdata[2]:.0f}%<br>Height %{customdata[3]:.0f} m<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=frame["wind_speed_ms"],
            y=pressure,
            mode="lines+markers",
            name="Wind",
            line={"color": "#047857", "width": 2},
            marker={
                "size": 11,
                "color": frame["wind_direction_deg"],
                "colorscale": "HSV",
                "cmin": 0,
                "cmax": 360,
                "colorbar": {"title": "direction", "x": 1.02, "len": 0.65},
            },
            customdata=np.column_stack([frame["wind_direction_deg"], frame["geopotential_height_m"]]),
            hovertemplate=(
                "Pressure %{y:.0f} hPa<br>Wind %{x:.1f} m/s"
                "<br>Direction %{customdata[0]:.0f} deg<br>Height %{customdata[1]:.0f} m<extra></extra>"
            ),
        ),
        row=1,
        col=2,
    )
    diagnostic_labels = [
        ("K index", profile.diagnostics.get("k_index"), ""),
        ("Total totals", profile.diagnostics.get("total_totals_index"), ""),
        ("SB CAPE", profile.diagnostics.get("surface_based_cape_j_kg"), " J/kg"),
        ("SB CIN", profile.diagnostics.get("surface_based_cin_j_kg"), " J/kg"),
        ("LCL", profile.diagnostics.get("lcl_height_m_asl"), " m"),
        ("PWAT", profile.diagnostics.get("precipitable_water_mm"), " mm"),
    ]
    diagnostic_text = "<br>".join(
        f"{label}: {value:.1f}{unit}" if value is not None and np.isfinite(value) else f"{label}: n/a"
        for label, value, unit in diagnostic_labels
    )
    fig.add_annotation(
        x=0.985,
        y=0.02,
        xref="paper",
        yref="paper",
        text=diagnostic_text,
        showarrow=False,
        align="left",
        bgcolor="rgba(255,255,255,0.90)",
        bordercolor="#d9e0ea",
        borderpad=8,
        font={"size": 12},
    )
    valid = profile.valid_time.strftime("%Y-%m-%d %H:%M UTC") if profile.valid_time is not None else "unknown time"
    fig.update_yaxes(
        type="log",
        autorange="reversed",
        tickvals=pressure,
        title_text="Pressure (hPa)",
        row=1,
        col=1,
    )
    fig.update_xaxes(title_text="Skewed temperature coordinate", row=1, col=1)
    fig.update_xaxes(title_text="Wind speed (m/s)", row=1, col=2)
    fig.update_layout(title=f"Interactive Skew-T Model Profile - Valid {valid}", height=820, hovermode="closest")
    return _save(fig, output)


def plot_climate_reference(
    climate: ClimateReference,
    output: Path,
) -> Path:
    standard = {item.metric: item for item in climate.standard_anomalies}
    recent = {item.metric: item for item in climate.recent_anomalies}
    metrics = [item.metric for item in climate.standard_anomalies]
    labels = [standard[metric].label for metric in metrics]
    fig = make_subplots(
        rows=2,
        cols=1,
        vertical_spacing=0.16,
        subplot_titles=(
            "Standardized Anomaly By Reference Period",
            "Percentile Across The Full ERA5 Record",
        ),
    )
    fig.add_trace(
        go.Bar(
            x=labels,
            y=[standard[metric].z_score for metric in metrics],
            name="1991-2020 standard normal",
            marker={"color": "#2563eb"},
            customdata=[standard[metric].anomaly for metric in metrics],
            hovertemplate="%{x}<br>%{y:+.2f} standard deviations<br>raw anomaly %{customdata:+.1f}<extra>1991-2020</extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=labels,
            y=[recent[metric].z_score for metric in metrics],
            name="Recent ten years",
            marker={"color": "#a16207"},
            customdata=[recent[metric].anomaly for metric in metrics],
            hovertemplate="%{x}<br>%{y:+.2f} standard deviations<br>raw anomaly %{customdata:+.1f}<extra>Recent decade</extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=labels,
            y=[climate.full_record_percentiles[metric] for metric in metrics],
            name="Full-record percentile",
            marker={
                "color": [climate.full_record_percentiles[metric] for metric in metrics],
                "colorscale": "RdBu_r",
                "cmin": 0,
                "cmax": 100,
            },
            text=[f"{climate.full_record_percentiles[metric]:.0f}th" for metric in metrics],
            textposition="outside",
            hovertemplate="%{x}<br>%{y:.0f}th percentile<extra>Full ERA5 record</extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=0, line_color="#667085", row=1, col=1)
    fig.add_hline(y=50, line_color="#667085", line_dash="dot", row=2, col=1)
    fig.update_yaxes(title_text="standard deviations", row=1, col=1)
    fig.update_yaxes(title_text="percentile", range=[0, 105], row=2, col=1)
    fig.update_layout(
        title="Climatological Reference Comparison",
        barmode="group",
        height=760,
    )
    return _save(fig, output)


def plot_land_surface(
    land: LandSurfaceAnalysis,
    output: Path,
    config: AtlasConfig,
) -> Path:
    if land.hourly.empty:
        return _empty_figure(
            "Land Surface And Water Balance",
            "Land-surface fields were unavailable for this reporting period.",
            output,
            760,
        )
    hourly = land.hourly.copy()
    hourly["local_time"] = pd.to_datetime(hourly["time"], utc=True).dt.tz_convert(
        config.location.timezone
    )
    daily = land.daily.copy()
    daily["local_time"] = pd.to_datetime(daily["time"], utc=True).dt.tz_convert(
        config.location.timezone
    )
    daily["cumulative_balance_mm"] = daily["water_balance_mm"].cumsum()
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.065,
        subplot_titles=(
            "Soil Temperature",
            "Volumetric Soil Moisture",
            "Atmospheric Demand And Reference ET0",
            "Daily And Cumulative Precipitation Minus ET0",
        ),
        specs=[[{}], [{}], [{"secondary_y": True}], [{"secondary_y": True}]],
    )
    depth_labels = ["0-7 cm", "7-28 cm", "28-100 cm", "100-255 cm"]
    colors = ["#b42318", "#d97706", "#047857", "#2563eb"]
    for column, label, color in zip(SOIL_TEMPERATURE_COLUMNS, depth_labels, colors):
        fig.add_trace(go.Scatter(x=hourly["local_time"], y=hourly[column], name=f"Soil T {label}", line={"color": color}), row=1, col=1)
    for column, label, color in zip(SOIL_MOISTURE_COLUMNS, depth_labels, colors):
        fig.add_trace(go.Scatter(x=hourly["local_time"], y=hourly[column], name=f"Soil moisture {label}", line={"color": color}), row=2, col=1)
    fig.add_trace(go.Scatter(x=hourly["local_time"], y=hourly["vapour_pressure_deficit"], name="VPD", line={"color": "#b42318"}), row=3, col=1, secondary_y=False)
    fig.add_trace(go.Bar(x=daily["local_time"], y=daily["et0_mm"], name="Daily ET0", marker={"color": "#d99100"}), row=3, col=1, secondary_y=True)
    fig.add_trace(go.Bar(x=daily["local_time"], y=daily["water_balance_mm"], name="Daily P - ET0", marker={"color": np.where(daily["water_balance_mm"] >= 0, "#2563eb", "#b42318")}), row=4, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=daily["local_time"], y=daily["cumulative_balance_mm"], name="Cumulative balance", line={"color": "#172033", "width": 2.5}), row=4, col=1, secondary_y=True)
    fig.update_yaxes(title_text="deg C", row=1, col=1)
    fig.update_yaxes(title_text="m3/m3", row=2, col=1)
    fig.update_yaxes(title_text="kPa", row=3, col=1, secondary_y=False)
    fig.update_yaxes(title_text="mm/day", row=3, col=1, secondary_y=True)
    fig.update_yaxes(title_text="mm/day", row=4, col=1, secondary_y=False)
    fig.update_yaxes(title_text="mm", row=4, col=1, secondary_y=True)
    fig.update_layout(title=f"Land Surface And Water Balance - {land.moisture_context}", height=900)
    return _save(fig, output)


def plot_phenomena_timeline(
    phenomena: PhenomenaAnalysis,
    output: Path,
    config: AtlasConfig,
) -> Path:
    if not phenomena.events:
        return _empty_figure(
            "Objective Weather-Phenomena Ledger",
            "No objective phenomenon met the reporting thresholds.",
            output,
            360,
        )
    fig = go.Figure()
    palette = ["#2563eb", "#b42318", "#047857", "#a16207", "#6d28d9", "#475467"]
    for index, event in enumerate(phenomena.events):
        start = event.start_time.tz_convert(config.location.timezone)
        end = event.end_time.tz_convert(config.location.timezone)
        fig.add_trace(
            go.Scatter(
                x=[start, end],
                y=[event.kind, event.kind],
                mode="lines+markers",
                line={"width": 10, "color": palette[index % len(palette)]},
                marker={"size": 7},
                name=event.kind,
                customdata=[[event.evidence, event.confidence, event.source]] * 2,
                hovertemplate=(
                    "%{y}<br>%{x}<br>%{customdata[0]}<br>Confidence %{customdata[1]:.0%}"
                    "<br>%{customdata[2]}<extra></extra>"
                ),
                showlegend=False,
            )
        )
    fig.update_layout(
        title="Objective Weather-Phenomena Chronology",
        height=max(360, min(720, 170 + len({event.kind for event in phenomena.events}) * 42)),
        xaxis_title="Local time",
        yaxis_title="",
        hovermode="closest",
    )
    return _save(fig, output)


def _wind_components(speed_ms: pd.Series, direction_deg: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    direction_rad = np.deg2rad(pd.to_numeric(direction_deg, errors="coerce").to_numpy(dtype=float))
    speed = pd.to_numeric(speed_ms, errors="coerce").to_numpy(dtype=float)
    return -speed * np.sin(direction_rad), -speed * np.cos(direction_rad)


def _bulk_shear(frame: pd.DataFrame, target_height_m: float) -> float:
    usable = frame.dropna(
        subset=["geopotential_height_m", "wind_speed_ms", "wind_direction_deg"]
    ).sort_values("geopotential_height_m")
    if len(usable) < 2:
        return float("nan")
    agl = usable["geopotential_height_m"].to_numpy(dtype=float)
    agl = agl - agl.min()
    if agl.max() < target_height_m:
        return float("nan")
    u, v = _wind_components(usable["wind_speed_ms"], usable["wind_direction_deg"])
    target_u = np.interp(target_height_m, agl, u)
    target_v = np.interp(target_height_m, agl, v)
    return float(np.hypot(target_u - u[0], target_v - v[0]))


def plot_hodograph(profile: ModelProfile, output: Path) -> Path:
    if profile.frame.empty:
        return _empty_figure(
            "Interactive Wind Hodograph",
            "Pressure-level wind data was unavailable for this reporting period.",
            output,
            720,
        )
    frame = profile.frame.dropna(
        subset=["wind_speed_ms", "wind_direction_deg", "geopotential_height_m"]
    ).sort_values("geopotential_height_m")
    if len(frame) < 4:
        return _empty_figure(
            "Interactive Wind Hodograph",
            "Too few pressure-level wind observations were available.",
            output,
            720,
        )
    u, v = _wind_components(frame["wind_speed_ms"], frame["wind_direction_deg"])
    height_agl_km = (
        frame["geopotential_height_m"] - frame["geopotential_height_m"].min()
    ) / 1000.0
    label_positions = {
        1000: "top left",
        850: "bottom right",
        700: "top left",
        500: "top right",
        300: "bottom left",
        200: "top left",
    }
    labels = [
        f"{int(level)} hPa" if int(level) in label_positions else ""
        for level in frame["pressure_hpa"]
    ]
    text_positions = [
        label_positions.get(int(level), "top center")
        for level in frame["pressure_hpa"]
    ]
    custom = np.column_stack(
        [
            frame["pressure_hpa"],
            height_agl_km,
            frame["wind_speed_ms"],
            frame["wind_direction_deg"],
        ]
    )
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=u,
            y=v,
            mode="lines+markers+text",
            text=labels,
            textposition=text_positions,
            name="Wind profile",
            line={"color": "#172033", "width": 2.5},
            marker={
                "size": 12,
                "color": height_agl_km,
                "colorscale": "Turbo",
                "colorbar": {"title": "km AGL"},
                "line": {"color": "#ffffff", "width": 1},
            },
            customdata=custom,
            hovertemplate=(
                "u %{x:.1f} m/s<br>v %{y:.1f} m/s"
                "<br>%{customdata[0]:.0f} hPa"
                "<br>%{customdata[1]:.1f} km AGL"
                "<br>Speed %{customdata[2]:.1f} m/s"
                "<br>From %{customdata[3]:.0f} deg<extra></extra>"
            ),
        )
    )
    shear_values = [
        ("0-1 km", _bulk_shear(frame, 1000)),
        ("0-3 km", _bulk_shear(frame, 3000)),
        ("0-6 km", _bulk_shear(frame, 6000)),
    ]
    shear_text = "<br>".join(
        f"{label} shear: {value:.1f} m/s" if np.isfinite(value) else f"{label} shear: n/a"
        for label, value in shear_values
    )
    fig.add_annotation(
        x=0.02,
        y=0.02,
        xref="paper",
        yref="paper",
        text=shear_text,
        showarrow=False,
        align="left",
        bgcolor="rgba(255,255,255,0.92)",
        bordercolor="#d9e0ea",
        borderpad=8,
    )
    extent = max(float(np.nanmax(np.abs(np.concatenate([u, v])))) + 3.0, 10.0)
    fig.add_hline(y=0, line_color="#98a2b3", line_width=1)
    fig.add_vline(x=0, line_color="#98a2b3", line_width=1)
    valid = (
        profile.valid_time.strftime("%Y-%m-%d %H:%M UTC")
        if profile.valid_time is not None
        else "unknown time"
    )
    fig.update_xaxes(
        title="West-east wind component u (m/s)",
        range=[-extent, extent],
        zeroline=False,
    )
    fig.update_yaxes(
        title="South-north wind component v (m/s)",
        range=[-extent, extent],
        scaleanchor="x",
        scaleratio=1,
        zeroline=False,
    )
    fig.update_layout(
        title=f"Interactive Wind Hodograph - Valid {valid}",
        height=760,
        hovermode="closest",
    )
    return _save(fig, output)


def plot_time_pressure_curtain(
    profile: ModelProfile,
    weather: pd.DataFrame,
    output: Path,
    config: AtlasConfig,
) -> Path:
    if profile.series.empty:
        return _empty_figure(
            "Debrecen Time-Pressure Curtain",
            "Pressure-level time-series data was unavailable for this reporting period.",
            output,
            760,
        )
    series = profile.series.copy()
    series["local_time"] = pd.to_datetime(series["time"], utc=True).dt.tz_convert(
        config.location.timezone
    )
    series["temperature_anomaly_c"] = series.groupby("pressure_hpa")[
        "temperature_c"
    ].transform(lambda values: values - values.mean())
    levels = sorted(series["pressure_hpa"].dropna().unique(), reverse=True)
    times = sorted(series["local_time"].dropna().unique())

    def matrix(column: str) -> np.ndarray:
        return (
            series.pivot_table(
                index="pressure_hpa",
                columns="local_time",
                values=column,
                aggfunc="mean",
            )
            .reindex(index=levels, columns=times)
            .to_numpy(dtype=float)
        )

    temperature = matrix("temperature_c")
    humidity = matrix("relative_humidity_pct")
    wind_speed = matrix("wind_speed_ms")
    wind_direction = matrix("wind_direction_deg")
    height = matrix("geopotential_height_m")
    temperature_anomaly = matrix("temperature_anomaly_c")
    custom = np.stack(
        [temperature, humidity, wind_speed, wind_direction, height],
        axis=-1,
    )

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.82, 0.18],
        specs=[[{}], [{"secondary_y": True}]],
        subplot_titles=("Atmospheric Evolution", "Surface Context"),
    )
    heatmaps = [
        (
            humidity,
            "Relative humidity",
            "Blues",
            0,
            100,
            "%",
            True,
        ),
        (
            temperature_anomaly,
            "Temperature anomaly",
            "RdBu_r",
            -8,
            8,
            "deg C",
            False,
        ),
        (
            wind_speed,
            "Wind speed",
            "Viridis",
            0,
            None,
            "m/s",
            False,
        ),
    ]
    for values, name, colorscale, zmin, zmax, unit, visible in heatmaps:
        fig.add_trace(
            go.Heatmap(
                x=times,
                y=levels,
                z=values,
                name=name,
                visible=visible,
                colorscale=colorscale,
                zmin=zmin,
                zmax=zmax,
                colorbar={"title": unit, "x": 1.01, "len": 0.68, "y": 0.62},
                customdata=custom,
                hovertemplate=(
                    "%{x}<br>%{y:.0f} hPa"
                    f"<br>{name}: %{{z:.1f}} {unit}"
                    "<br>Temperature %{customdata[0]:.1f} deg C"
                    "<br>RH %{customdata[1]:.0f}%"
                    "<br>Wind %{customdata[2]:.1f} m/s from %{customdata[3]:.0f} deg"
                    "<br>Height %{customdata[4]:.0f} m<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )

    surface = _prepare(weather, config.location.timezone)
    fig.add_trace(
        go.Scatter(
            x=surface["local_time"],
            y=surface["pressure_msl"],
            name="Sea-level pressure",
            line={"color": "#172033", "width": 2},
        ),
        row=2,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            x=surface["local_time"],
            y=surface["precipitation"],
            name="Precipitation",
            marker={"color": "#2563eb"},
            opacity=0.65,
        ),
        row=2,
        col=1,
        secondary_y=True,
    )
    fig.update_layout(
        title="Debrecen 72-Hour Time-Pressure Curtain",
        height=820,
        hovermode="closest",
        updatemenus=[
            {
                "type": "dropdown",
                "direction": "down",
                "x": 0.01,
                "y": 1.12,
                "showactive": True,
                "buttons": [
                    {
                        "label": "Relative humidity",
                        "method": "update",
                        "args": [{"visible": [True, False, False, True, True]}],
                    },
                    {
                        "label": "Temperature anomaly",
                        "method": "update",
                        "args": [{"visible": [False, True, False, True, True]}],
                    },
                    {
                        "label": "Wind speed",
                        "method": "update",
                        "args": [{"visible": [False, False, True, True, True]}],
                    },
                ],
            }
        ],
    )
    fig.update_yaxes(
        title_text="Pressure (hPa)",
        type="log",
        autorange="reversed",
        tickvals=levels,
        row=1,
        col=1,
    )
    fig.update_yaxes(title_text="hPa", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="mm/h", row=2, col=1, secondary_y=True)
    return _save(fig, output)


def plot_station_comparison(
    station: StationObservations,
    model: pd.DataFrame,
    output: Path,
    config: AtlasConfig,
) -> Path:
    observed = station_hourly(station)
    if observed.empty:
        return _empty_figure(
            "Debrecen Airport Observation Ledger",
            "HungaroMet station observations were unavailable for this reporting period.",
            output,
            720,
        )
    observed["local_time"] = pd.to_datetime(observed["time"], utc=True).dt.tz_convert(
        config.location.timezone
    )
    gridded = _prepare(model, config.location.timezone)
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.055,
        subplot_titles=("Temperature", "Sea-Level Pressure", "Wind And Gust", "Precipitation"),
    )
    fig.add_trace(go.Scatter(x=observed["local_time"], y=observed["temperature_c"], name="Station temperature", line={"color": "#b42318", "width": 2.5}), row=1, col=1)
    fig.add_trace(go.Scatter(x=gridded["local_time"], y=gridded["temperature_2m"], name="Gridded temperature", line={"color": "#b42318", "dash": "dot"}), row=1, col=1)
    fig.add_trace(go.Scatter(x=observed["local_time"], y=observed["pressure_msl_hpa"], name="Station pressure", line={"color": "#344054", "width": 2.5}), row=2, col=1)
    fig.add_trace(go.Scatter(x=gridded["local_time"], y=gridded["pressure_msl"], name="Gridded pressure", line={"color": "#667085", "dash": "dot"}), row=2, col=1)
    fig.add_trace(go.Scatter(x=observed["local_time"], y=observed["wind_speed_ms"], name="Station wind", line={"color": "#047857"}), row=3, col=1)
    fig.add_trace(go.Scatter(x=observed["local_time"], y=observed["wind_gust_ms"], name="Station gust", line={"color": "#101828"}), row=3, col=1)
    fig.add_trace(go.Bar(x=observed["local_time"], y=observed["precipitation_mm"], name="Station precipitation", marker={"color": "#2563eb"}), row=4, col=1)
    fig.add_trace(go.Scatter(x=gridded["local_time"], y=gridded["precipitation"], name="Gridded precipitation", mode="lines", line={"color": "#60a5fa", "dash": "dot"}), row=4, col=1)
    fig.update_yaxes(title_text="deg C", row=1, col=1)
    fig.update_yaxes(title_text="hPa", row=2, col=1)
    fig.update_yaxes(title_text="m/s", row=3, col=1)
    fig.update_yaxes(title_text="mm/h", row=4, col=1)
    fig.update_layout(title=f"Observed At {station.station_name} - Station Versus Gridded Context", height=820)
    return _save(fig, output)


RADAR_COLORSCALE = [
    [0.00, "rgba(255,255,255,0)"],
    [0.12, "#c7e9f1"],
    [0.28, "#4db6e2"],
    [0.43, "#2676c9"],
    [0.57, "#3da65a"],
    [0.70, "#f0d33c"],
    [0.82, "#f28e2b"],
    [0.92, "#d73027"],
    [1.00, "#7f0000"],
]


def plot_radar_archive(radar: RadarArchive, output: Path, config: AtlasConfig) -> Path:
    if radar.reflectivity_dbz.size == 0:
        return _empty_figure(
            "Debrecen Radar Replay And Accumulation",
            "HungaroMet composite radar frames were unavailable for this reporting period.",
            output,
            720,
        )
    stride = 2
    latitudes = radar.latitudes[::stride]
    longitudes = radar.longitudes[::stride]
    replay = radar.reflectivity_dbz[:, ::stride, ::stride]
    accumulation = radar.accumulation_mm[::stride, ::stride]
    local_times = [timestamp.tz_convert(config.location.timezone) for timestamp in radar.times]
    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.58, 0.42],
        horizontal_spacing=0.10,
        subplot_titles=("Composite Reflectivity Replay", "Radar-Derived Accumulation Proxy"),
    )
    fig.add_trace(
        go.Heatmap(
            x=longitudes,
            y=latitudes,
            z=replay[0],
            zmin=0,
            zmax=65,
            colorscale=RADAR_COLORSCALE,
            colorbar={"title": "dBZ", "x": 0.55, "len": 0.8},
            hovertemplate="%{y:.2f} N, %{x:.2f} E<br>%{z:.1f} dBZ<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Heatmap(
            x=longitudes,
            y=latitudes,
            z=accumulation,
            zmin=0,
            colorscale="Blues",
            colorbar={"title": "mm", "x": 1.01, "len": 0.8},
            hovertemplate="%{y:.2f} N, %{x:.2f} E<br>%{z:.1f} mm proxy<extra></extra>",
        ),
        row=1,
        col=2,
    )
    for column in [1, 2]:
        fig.add_trace(
            go.Scatter(
                x=[config.location.longitude],
                y=[config.location.latitude],
                mode="markers+text",
                text=["Debrecen"],
                textposition="top center",
                marker={"symbol": "x", "size": 11, "color": "#111827"},
                showlegend=False,
                hoverinfo="skip",
            ),
            row=1,
            col=column,
        )
    frames = [
        go.Frame(
            name=timestamp.strftime("%Y-%m-%d %H:%M"),
            data=[go.Heatmap(z=field)],
            traces=[0],
        )
        for timestamp, field in zip(local_times, replay)
    ]
    fig.frames = frames
    fig.update_layout(
        title=f"HungaroMet Radar Event Reconstruction - {local_times[0].strftime('%Y-%m-%d %H:%M %Z')}",
        height=720,
        updatemenus=[
            {
                "type": "buttons",
                "direction": "left",
                "x": 0.0,
                "y": 1.10,
                "buttons": [
                    {"label": "Play", "method": "animate", "args": [None, {"frame": {"duration": 450, "redraw": True}, "transition": {"duration": 0}, "fromcurrent": True}]},
                    {"label": "Pause", "method": "animate", "args": [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}]},
                ],
            }
        ],
        sliders=[
            {
                "active": 0,
                "currentvalue": {"prefix": "Local time: "},
                "steps": [
                    {"label": timestamp.strftime("%d %Hh"), "method": "animate", "args": [[frame.name], {"mode": "immediate", "frame": {"duration": 0, "redraw": True}}]}
                    for timestamp, frame in zip(local_times, frames)
                ],
            }
        ],
    )
    for column in [1, 2]:
        fig.update_xaxes(title_text="Longitude", row=1, col=column)
        fig.update_yaxes(title_text="Latitude", scaleanchor=f"x{column if column > 1 else ''}", row=1, col=column)
    return _save(fig, output)


def plot_lightning_diary(lightning: LightningArchive, output: Path, config: AtlasConfig) -> Path:
    if lightning.frame.empty:
        unavailable = any("unavailable" in note.lower() for note in lightning.notes)
        return _empty_figure(
            "Debrecen Lightning Diary",
            (
                "HungaroMet LINET data was unavailable for this reporting period."
                if unavailable
                else "No lightning events were detected within 150 km of Debrecen during the reporting period."
            ),
            output,
            620,
        )
    frame = lightning.frame
    if len(frame) > 6000:
        frame = frame.iloc[np.linspace(0, len(frame) - 1, 6000).astype(int)]
    local_time = pd.to_datetime(frame["time"], utc=True).dt.tz_convert(config.location.timezone)
    hourly = lightning.hourly.copy()
    hourly["local_time"] = pd.to_datetime(hourly["time"], utc=True).dt.tz_convert(config.location.timezone)
    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.58, 0.42],
        horizontal_spacing=0.10,
        subplot_titles=("LINET Events Around Debrecen", "Hourly Lightning Rhythm"),
    )
    fig.add_trace(
        go.Scattergl(
            x=frame["longitude"],
            y=frame["latitude"],
            mode="markers",
            marker={
                "size": np.clip(np.abs(frame["peak_current_ka"]) / 8.0 + 3.0, 3.0, 12.0),
                "color": frame["peak_current_ka"],
                "colorscale": "RdBu_r",
                "cmid": 0,
                "colorbar": {"title": "kA", "x": 0.55, "len": 0.8},
                "opacity": 0.65,
            },
            customdata=np.column_stack([local_time.astype(str), frame["distance_km"]]),
            hovertemplate="%{customdata[0]}<br>%{y:.3f} N, %{x:.3f} E<br>%{marker.color:.1f} kA<br>%{customdata[1]:.0f} km from Debrecen<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=[config.location.longitude], y=[config.location.latitude], mode="markers+text", text=["Debrecen"], textposition="top center", marker={"symbol": "x", "size": 12, "color": "#111827"}, showlegend=False),
        row=1,
        col=1,
    )
    fig.add_trace(go.Bar(x=hourly["local_time"], y=hourly["flash_count"], marker={"color": "#6d28d9"}, name="Events"), row=1, col=2)
    fig.update_xaxes(title_text="Longitude", row=1, col=1)
    fig.update_yaxes(title_text="Latitude", scaleanchor="x", row=1, col=1)
    fig.update_xaxes(title_text="Local time", row=1, col=2)
    fig.update_yaxes(title_text="events per hour", row=1, col=2)
    fig.update_layout(title="HungaroMet LINET Lightning Diary", height=620, hovermode="closest")
    return _save(fig, output)


def plot_satellite_diary(
    satellite: SatelliteArchive,
    radar: RadarArchive,
    lightning: LightningArchive,
    output: Path,
    config: AtlasConfig,
) -> Path:
    if satellite.frame_count == 0:
        return _empty_figure(
            "Meteosat Satellite, Radar And Lightning Diary",
            "HungaroMet Meteosat frames were unavailable for this reporting period.",
            output,
            820,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    media_dir = output.parent / "satellite_media"
    media_dir.mkdir(parents=True, exist_ok=True)
    products: dict[str, list[dict[str, str]]] = {}
    for product, frames in satellite.frames.items():
        encoded = []
        for frame in frames:
            target = media_dir / f"{product}_{frame.time.strftime('%Y%m%d_%H%M')}.webp"
            if not target.exists():
                with Image.open(frame.path) as image:
                    image = image.convert("RGB")
                    if image.width > config.satellite.image_width_px:
                        height = round(image.height * config.satellite.image_width_px / image.width)
                        image = image.resize(
                            (config.satellite.image_width_px, height), Image.Resampling.LANCZOS
                        )
                    image.save(
                        target,
                        "WEBP",
                        quality=config.satellite.webp_quality,
                        method=6,
                    )
            encoded.append(
                {
                    "time": frame.time.isoformat(),
                    "src": f"satellite_media/{target.name}",
                }
            )
        products[product] = encoded

    radar_rows = []
    if not radar.timeline.empty:
        for row in radar.timeline.to_dict("records"):
            radar_rows.append(
                {
                    "time": pd.Timestamp(row["time"]).isoformat(),
                    "maximum": (
                        None if pd.isna(row.get("domain_max_dbz")) else float(row["domain_max_dbz"])
                    ),
                    "debrecen": (
                        None if pd.isna(row.get("reflectivity_dbz")) else float(row["reflectivity_dbz"])
                    ),
                }
            )
    lightning_rows = []
    if not lightning.hourly.empty:
        for row in lightning.hourly.to_dict("records"):
            lightning_rows.append(
                {
                    "time": pd.Timestamp(row["time"]).isoformat(),
                    "count": int(row["flash_count"]),
                }
            )
    payload = json.dumps(
        {"products": products, "radar": radar_rows, "lightning": lightning_rows},
        allow_nan=False,
    )
    output.write_text(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Meteosat Satellite Diary</title><script src="https://cdn.plot.ly/plotly-3.0.1.min.js"></script>
<style>
*{{box-sizing:border-box}} body{{margin:0;padding:18px;font-family:Inter,Segoe UI,Arial,sans-serif;color:#172033;background:#fff}}
.toolbar{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}} select,button{{height:36px;border:1px solid #cfd7e3;background:#fff;color:#172033;padding:0 11px;font:inherit}} button{{cursor:pointer}} input[type=range]{{flex:1;min-width:240px}}
.layout{{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(300px,.85fr);gap:16px}} .image-wrap{{background:#0b0f17;min-height:540px;display:grid;place-items:center;overflow:hidden}} #satellite{{display:block;max-width:100%;max-height:620px;object-fit:contain}} .status{{padding:12px 0;color:#475467;font-size:14px}} #timeline{{height:560px}} .stamp{{font-weight:700;min-width:185px}} @media(max-width:800px){{.layout{{grid-template-columns:1fr}} .image-wrap{{min-height:380px}} #timeline{{height:420px}}}}
</style></head><body>
<div class="toolbar"><label for="product">Product</label><select id="product"></select><button id="play" type="button">Play</button><button id="pause" type="button">Pause</button><button id="zoom-out" type="button" title="Zoom out" aria-label="Zoom out">-</button><button id="zoom-in" type="button" title="Zoom in" aria-label="Zoom in">+</button><button id="zoom-reset" type="button" title="Reset zoom" aria-label="Reset zoom">1:1</button><input id="frame" type="range" min="0" max="0" value="0"><span class="stamp" id="stamp"></span></div>
<div class="layout"><div><div class="image-wrap"><img id="satellite" alt="HungaroMet Meteosat satellite product"></div><div class="status" id="status"></div></div><div id="timeline"></div></div>
<script>
const data={payload}; const product=document.getElementById('product'); const slider=document.getElementById('frame'); const image=document.getElementById('satellite'); const stamp=document.getElementById('stamp'); const status=document.getElementById('status'); let timer=null; let zoom=1;
Object.keys(data.products).forEach(name=>{{const option=document.createElement('option');option.value=name;option.textContent=name;product.appendChild(option)}});
function nearest(rows,time){{if(!rows.length)return null;const target=Date.parse(time);return rows.reduce((best,row)=>Math.abs(Date.parse(row.time)-target)<Math.abs(Date.parse(best.time)-target)?row:best)}}
function drawTimeline(){{Plotly.newPlot('timeline',[{{x:data.radar.map(d=>d.time),y:data.radar.map(d=>d.maximum),name:'Radar maximum',type:'scatter',line:{{color:'#b42318'}}}},{{x:data.lightning.map(d=>d.time),y:data.lightning.map(d=>d.count),name:'LINET events',type:'bar',yaxis:'y2',marker:{{color:'#6d28d9'}}}}],{{title:'Synchronized event timeline',margin:{{l:52,r:50,t:56,b:48}},hovermode:'x unified',xaxis:{{title:'UTC'}},yaxis:{{title:'dBZ'}},yaxis2:{{title:'events/h',overlaying:'y',side:'right'}},legend:{{orientation:'h'}}}},{{displaylogo:false,responsive:true,scrollZoom:true}})}}
function applyZoom(){{image.style.transform=`scale(${{zoom}})`}}
function render(){{const frames=data.products[product.value]||[];if(!frames.length)return;slider.max=String(frames.length-1);slider.value=String(Math.min(Number(slider.value),frames.length-1));const frame=frames[Number(slider.value)];image.src=frame.src;const local=new Date(frame.time);stamp.textContent=local.toLocaleString('en-GB',{{timeZone:'Europe/Budapest',dateStyle:'medium',timeStyle:'short'}});const radar=nearest(data.radar,frame.time);const flash=nearest(data.lightning,frame.time);status.textContent=`${{product.value}} valid ${{local.toISOString().slice(0,16).replace('T',' ')}} UTC | nearest radar maximum ${{radar&&radar.maximum!=null?Number(radar.maximum).toFixed(1):'n/a'}} dBZ | nearest LINET hour ${{flash?flash.count:0}} event(s)`;Plotly.relayout('timeline',{{shapes:[{{type:'line',x0:frame.time,x1:frame.time,y0:0,y1:1,yref:'paper',line:{{color:'#111827',width:2}}}}]}})}}
function setZoom(value){{zoom=Math.min(4,Math.max(1,value));applyZoom()}}
product.addEventListener('change',()=>{{slider.value='0';setZoom(1);render()}});slider.addEventListener('input',render);document.getElementById('play').addEventListener('click',()=>{{clearInterval(timer);timer=setInterval(()=>{{const max=Number(slider.max);slider.value=String((Number(slider.value)+1)%(max+1));render()}},650)}});document.getElementById('pause').addEventListener('click',()=>clearInterval(timer));document.getElementById('zoom-in').addEventListener('click',()=>setZoom(zoom+0.25));document.getElementById('zoom-out').addEventListener('click',()=>setZoom(zoom-0.25));document.getElementById('zoom-reset').addEventListener('click',()=>setZoom(1));image.addEventListener('wheel',event=>{{event.preventDefault();setZoom(zoom+(event.deltaY < 0 ? 0.25 : -0.25))}},{{passive:false}});drawTimeline();render();
</script></body></html>""",
        encoding="utf-8",
    )
    return output


def plot_column_diagnostics(profile: ModelProfile, output: Path, config: AtlasConfig) -> Path:
    if profile.surface_series.empty:
        return _empty_figure(
            "Parcel And Boundary-Layer Evolution",
            "Model parcel and boundary-layer time series were unavailable.",
            output,
            720,
        )
    frame = profile.surface_series.copy()
    frame["local_time"] = pd.to_datetime(frame["time"], utc=True).dt.tz_convert(config.location.timezone)
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        subplot_titles=("CAPE And CIN", "Boundary Layer", "Column Moisture", "Freezing Level And Wet Bulb"),
        specs=[[{}], [{}], [{}], [{"secondary_y": True}]],
    )
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["cape"], name="CAPE", fill="tozeroy", line={"color": "#b42318"}), row=1, col=1)
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["convective_inhibition"], name="CIN", line={"color": "#2563eb"}), row=1, col=1)
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["boundary_layer_height"], name="PBL height", line={"color": "#a16207"}), row=2, col=1)
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["total_column_integrated_water_vapour"], name="Column water", line={"color": "#0891b2"}), row=3, col=1)
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["freezing_level_height"], name="Freezing level", line={"color": "#475467"}), row=4, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["wet_bulb_temperature_2m"], name="2 m wet bulb", line={"color": "#047857", "dash": "dot"}), row=4, col=1, secondary_y=True)
    fig.update_yaxes(title_text="J/kg", row=1, col=1)
    fig.update_yaxes(title_text="m AGL", row=2, col=1)
    fig.update_yaxes(title_text="kg/m2", row=3, col=1)
    fig.update_yaxes(title_text="m ASL", row=4, col=1, secondary_y=False)
    fig.update_yaxes(title_text="deg C", row=4, col=1, secondary_y=True)
    fig.update_layout(title="Parcel, Moisture And Boundary-Layer Evolution", height=780)
    return _save(fig, output)


def plot_synoptic_evolution(synoptic: SynopticArchive, output: Path, config: AtlasConfig) -> Path:
    if not synoptic.times:
        return _empty_figure(
            "Central European Synoptic Evolution",
            "Gridded pressure-level analysis was unavailable for this reporting period.",
            output,
            720,
        )
    local_times = [timestamp.tz_convert(config.location.timezone) for timestamp in synoptic.times]

    def traces(index: int) -> list[go.BaseTraceType]:
        longitude_grid, latitude_grid = np.meshgrid(
            synoptic.longitudes[::2], synoptic.latitudes[::2]
        )
        quiver = ff.create_quiver(
            longitude_grid.ravel(),
            latitude_grid.ravel(),
            synoptic.wind_u_850ms[index, ::2, ::2].ravel(),
            synoptic.wind_v_850ms[index, ::2, ::2].ravel(),
            scale=0.035,
            arrow_scale=0.28,
            line={"color": "rgba(17, 24, 39, 0.68)", "width": 1},
        ).data[0]
        quiver.name = "850 hPa wind"
        quiver.showlegend = True
        quiver.hoverinfo = "skip"
        return [
            go.Contour(name="850 hPa temperature", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.temperature_850c[index], colorscale="RdBu_r", zmid=0, contours={"showlines": False}, colorbar={"title": "850 T C"}, hovertemplate="%{y:.1f} N %{x:.1f} E<br>850 T %{z:.1f} C<extra></extra>"),
            go.Contour(name="MSLP", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.pressure_msl_hpa[index], contours={"coloring": "none", "showlabels": True, "start": 980, "end": 1040, "size": 4}, line={"color": "#172033", "width": 1.5}, showscale=False, hovertemplate="MSLP %{z:.0f} hPa<extra></extra>"),
            go.Contour(name="500 hPa height", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.height_500m[index], contours={"coloring": "none", "showlabels": True, "size": 60}, line={"color": "#7c2d12", "width": 1.5, "dash": "dash"}, showscale=False, hovertemplate="500 hPa height %{z:.0f} m<extra></extra>"),
            quiver,
            go.Contour(name="300 hPa wind", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.wind_speed_300ms[index], colorscale="Turbo", zmin=15, zmax=65, contours={"showlines": False}, colorbar={"title": "300 wind m/s"}, hovertemplate="300 hPa wind %{z:.1f} m/s<extra></extra>"),
            go.Contour(name="300 hPa height", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.height_300m[index], contours={"coloring": "none", "showlabels": True, "size": 90}, line={"color": "#111827", "width": 1.4}, showscale=False, hovertemplate="300 hPa height %{z:.0f} m<extra></extra>"),
            go.Contour(name="500 hPa vorticity", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.vorticity_500_1e5_s[index], colorscale="PuOr_r", zmid=0, contours={"showlines": False}, colorbar={"title": "vorticity 1e-5 s-1"}, hovertemplate="500 hPa vorticity %{z:.1f} x10^-5 s^-1<extra></extra>"),
            go.Contour(name="500 hPa height", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.height_500m[index], contours={"coloring": "none", "showlabels": True, "size": 60}, line={"color": "#172033", "width": 1.4}, showscale=False, hovertemplate="500 hPa height %{z:.0f} m<extra></extra>"),
            go.Contour(name="700 hPa humidity", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.relative_humidity_700pct[index], colorscale="Blues", zmin=0, zmax=100, contours={"showlines": False}, colorbar={"title": "700 RH %"}, hovertemplate="700 hPa RH %{z:.0f}%<extra></extra>"),
            go.Contour(name="700 hPa vertical velocity", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.vertical_velocity_700ms[index] * 100.0, contours={"coloring": "lines", "showlabels": True, "start": -20, "end": 20, "size": 2}, line={"color": "#b42318", "width": 1.3}, showscale=False, hovertemplate="700 hPa vertical velocity %{z:.1f} cm/s<extra></extra>"),
            go.Contour(name="850 hPa theta-e", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.theta_e_850k[index], colorscale="Spectral_r", contours={"showlines": False}, colorbar={"title": "theta-e K"}, hovertemplate="850 hPa theta-e %{z:.1f} K<extra></extra>"),
            go.Contour(name="850 hPa thermal advection", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.temperature_advection_850c_3h[index], contours={"coloring": "lines", "showlabels": True, "start": -8, "end": 8, "size": 1}, line={"color": "#111827", "width": 1.1}, showscale=False, hovertemplate="850 hPa advection %{z:.1f} K/3h<extra></extra>"),
            go.Contour(name="850 hPa frontogenesis", x=synoptic.longitudes, y=synoptic.latitudes, z=synoptic.frontogenesis_850k_100km_3h[index], contours={"coloring": "none", "showlabels": False, "start": 0.5, "end": 8, "size": 0.5}, line={"color": "#b42318", "width": 2}, showscale=False, hovertemplate="850 hPa frontogenesis %{z:.2f} K/(100 km 3h)<extra></extra>"),
        ]

    mode_groups = {
        "Air mass / surface": {0, 1, 2, 3},
        "300 hPa jet": {4, 5},
        "500 hPa vorticity": {6, 7},
        "700 hPa moisture / ascent": {8, 9},
        "850 hPa theta-e / fronts": {10, 11, 12},
    }
    initial = traces(0)
    for trace_index, trace in enumerate(initial):
        trace.visible = trace_index in mode_groups["Air mass / surface"]
    fig = go.Figure(data=initial)
    fig.add_trace(go.Scatter(x=[config.location.longitude], y=[config.location.latitude], mode="markers+text", text=["Debrecen"], textposition="top center", marker={"symbol": "x", "size": 12, "color": "#111827"}, showlegend=False))
    frames = [go.Frame(name=timestamp.strftime("%Y-%m-%d %H:%M"), data=traces(index), traces=list(range(13))) for index, timestamp in enumerate(local_times)]
    fig.frames = frames
    layer_buttons = []
    for label, active_indices in mode_groups.items():
        visibility = [index in active_indices for index in range(13)] + [True]
        layer_buttons.append({"label": label, "method": "update", "args": [{"visible": visibility}, {"title": f"Central European Synoptic Dynamics - {label}"}]})
    fig.update_layout(
        title="Central European Synoptic Dynamics - Air mass / surface",
        height=720,
        xaxis_title="Longitude",
        yaxis_title="Latitude",
        yaxis={"scaleanchor": "x"},
        updatemenus=[
            {"type": "dropdown", "direction": "down", "x": 0.0, "y": 1.17, "buttons": layer_buttons},
            {"type": "buttons", "direction": "left", "x": 0.42, "y": 1.17, "buttons": [{"label": "Play", "method": "animate", "args": [None, {"frame": {"duration": 700, "redraw": True}, "fromcurrent": True}]}, {"label": "Pause", "method": "animate", "args": [[None], {"mode": "immediate", "frame": {"duration": 0}}]}]},
        ],
        sliders=[{"currentvalue": {"prefix": "Local time: "}, "steps": [{"label": timestamp.strftime("%d %Hh"), "method": "animate", "args": [[frame.name], {"mode": "immediate", "frame": {"duration": 0, "redraw": True}}]} for timestamp, frame in zip(local_times, frames)]}],
    )
    return _save(fig, output)


def plot_physical_energy(energy: PhysicalEnergy, output: Path, config: AtlasConfig) -> Path:
    if energy.series.empty:
        return _empty_figure("Physical Renewable Yield", "Physical PV and wind calculations were unavailable.", output, 680)
    frame = energy.series.copy()
    frame["local_time"] = pd.to_datetime(frame["time"], utc=True).dt.tz_convert(config.location.timezone)
    frame["pv_cumulative_kwh_kwp"] = frame["pv_power_kw_per_kwp"].cumsum()
    frame["wind_cumulative_flh"] = frame["wind_capacity_factor"].cumsum()
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07, subplot_titles=("Reference PV Output", "Reference Wind Turbine", "Cumulative Weather Yield"), specs=[[{"secondary_y": True}], [{"secondary_y": True}], [{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["pv_power_kw_per_kwp"], name="PV kW/kWp", fill="tozeroy", line={"color": "#d99100"}), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["pv_cell_temperature_c"], name="Cell temperature", line={"color": "#b42318", "dash": "dot"}), row=1, col=1, secondary_y=True)
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["wind_capacity_factor"] * 100.0, name="Wind capacity factor", fill="tozeroy", line={"color": "#047857"}), row=2, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["wind_power_density_w_m2"], name="Power density", line={"color": "#2563eb", "dash": "dot"}), row=2, col=1, secondary_y=True)
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["pv_cumulative_kwh_kwp"], name="PV cumulative", line={"color": "#d99100", "width": 3}), row=3, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=frame["local_time"], y=frame["wind_cumulative_flh"], name="Wind full-load hours", line={"color": "#047857", "width": 3}), row=3, col=1, secondary_y=True)
    fig.update_yaxes(title_text="kW/kWp", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="deg C", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="%", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="W/m2", row=2, col=1, secondary_y=True)
    fig.update_yaxes(title_text="kWh/kWp", row=3, col=1, secondary_y=False)
    fig.update_yaxes(title_text="full-load h", row=3, col=1, secondary_y=True)
    fig.update_layout(title="Physically Based PV And Wind Weather Yield", height=760)
    return _save(fig, output)


def generate_all_figures(
    frame: pd.DataFrame,
    context_frame: pd.DataFrame,
    climate: ClimateReference,
    daily_climate: ClimateReference,
    land: LandSurfaceAnalysis,
    phenomena: PhenomenaAnalysis,
    daily_frame: pd.DataFrame,
    anomalies: list[Anomaly],
    electricity: pd.DataFrame,
    electricity_summary: ElectricitySummary,
    profile: ModelProfile,
    station: StationObservations,
    radar: RadarArchive,
    lightning: LightningArchive,
    satellite: SatelliteArchive,
    fronts: FrontAnalysis,
    synoptic: SynopticArchive,
    physical_energy: PhysicalEnergy,
    daily_physical_energy: PhysicalEnergy,
    regime: RegimeClassification,
    current_start: date,
    output_dir: Path,
    config: AtlasConfig,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "meteogram": plot_meteogram(frame, output_dir / "meteogram.html", config, fronts),
        "daily_meteogram": plot_meteogram(
            daily_frame,
            output_dir / "daily_meteogram.html",
            config,
            title="Yesterday At Debrecen - Interactive Meteogram",
        ),
        "station_comparison": plot_station_comparison(
            station, frame, output_dir / "station_comparison.html", config
        ),
        "radar_archive": plot_radar_archive(radar, output_dir / "radar_archive.html", config),
        "lightning_diary": plot_lightning_diary(
            lightning, output_dir / "lightning_diary.html", config
        ),
        "satellite_diary": plot_satellite_diary(
            satellite,
            radar,
            lightning,
            output_dir / "satellite_diary.html",
            config,
        ),
        "synoptic_evolution": plot_synoptic_evolution(
            synoptic, output_dir / "synoptic_evolution.html", config
        ),
        "physical_energy": plot_physical_energy(
            physical_energy, output_dir / "physical_energy.html", config
        ),
        "daily_physical_energy": plot_physical_energy(
            daily_physical_energy, output_dir / "daily_physical_energy.html", config
        ),
        "seven_day_context": plot_seven_day_context(
            context_frame,
            current_start,
            output_dir / "seven_day_context.html",
            config,
        ),
        "wind_rose": plot_wind_rose(frame, output_dir / "wind_rose.html", config),
        "pressure_tendency": plot_pressure_tendency(frame, output_dir / "pressure_tendency.html", config),
        "dewpoint_spread": plot_dewpoint_spread(frame, output_dir / "dewpoint_spread.html", config),
        "solar_diurnal": plot_solar_diurnal(frame, climate, output_dir / "solar_diurnal.html", config),
        "anomaly_bars": plot_anomaly_bars(anomalies, output_dir / "anomaly_bars.html"),
        "climate_reference": plot_climate_reference(
            climate, output_dir / "climate_reference.html"
        ),
        "daily_climate_reference": plot_climate_reference(
            daily_climate, output_dir / "daily_climate_reference.html"
        ),
        "land_surface": plot_land_surface(
            land, output_dir / "land_surface.html", config
        ),
        "phenomena_timeline": plot_phenomena_timeline(
            phenomena, output_dir / "phenomena_timeline.html", config
        ),
        "regime_strip": plot_regime_strip(frame, regime, output_dir / "regime_strip.html", config),
        "electricity_overview": plot_electricity_overview(
            electricity,
            output_dir / "electricity_overview.html",
            config,
        ),
        "weather_electricity_links": plot_weather_electricity_links(
            frame,
            electricity,
            output_dir / "weather_electricity_links.html",
        ),
        "model_profile": plot_model_profile(profile, output_dir / "model_profile.html"),
        "column_diagnostics": plot_column_diagnostics(
            profile, output_dir / "column_diagnostics.html", config
        ),
        "hodograph": plot_hodograph(profile, output_dir / "hodograph.html"),
        "time_pressure": plot_time_pressure_curtain(
            profile,
            frame,
            output_dir / "time_pressure.html",
            config,
        ),
    }
