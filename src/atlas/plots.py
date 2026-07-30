from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from atlas.anomalies import Anomaly
from atlas.config import AtlasConfig
from atlas.electricity import ElectricitySummary
from atlas.energy import EnergyIndex
from atlas.profile import ModelProfile
from atlas.regimes import RegimeClassification


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
    fig.update_layout(
        template="plotly_white",
        font={"family": "Inter, Segoe UI, Arial, sans-serif", "color": "#172033"},
        margin={"l": 58, "r": 26, "t": 64, "b": 48},
        hovermode="x unified",
        dragmode="zoom",
    )
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


def plot_meteogram(frame: pd.DataFrame, output: Path, config: AtlasConfig) -> Path:
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
    fig.update_layout(title="Rolling 72-Hour Interactive Meteogram", height=980)
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
    fig.update_layout(title="Seven-Day Weather Context · Highlighted Area Is The Current Report", height=720)
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


def plot_solar_diurnal(frame: pd.DataFrame, baseline: pd.DataFrame, output: Path, config: AtlasConfig) -> Path:
    current = _prepare(frame, config.location.timezone)
    base = _prepare(baseline, config.location.timezone)
    current["date"] = current["local_time"].dt.date
    current["hour"] = current["local_time"].dt.hour + current["local_time"].dt.minute / 60
    base["hour"] = base["local_time"].dt.hour
    typical = base.groupby("hour")["shortwave_radiation"].median()

    fig = go.Figure()
    for day, group in current.groupby("date"):
        fig.add_trace(go.Scatter(x=group["hour"], y=group["shortwave_radiation"], mode="lines", name=str(day), opacity=0.7))
    fig.add_trace(go.Scatter(x=typical.index, y=typical.values, mode="lines", name="baseline median", line={"color": "#111827", "width": 4}))
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


def plot_energy_quadrant(energy: EnergyIndex, output: Path) -> Path:
    fig = go.Figure()
    fig.add_shape(type="rect", x0=0, x1=50, y0=50, y1=100, fillcolor="#e0f2fe", line_width=0)
    fig.add_shape(type="rect", x0=50, x1=100, y0=50, y1=100, fillcolor="#dcfce7", line_width=0)
    fig.add_shape(type="rect", x0=0, x1=50, y0=0, y1=50, fillcolor="#f3f4f6", line_width=0)
    fig.add_shape(type="rect", x0=50, x1=100, y0=0, y1=50, fillcolor="#fef3c7", line_width=0)
    fig.add_hline(y=50, line_color="#9ca3af")
    fig.add_vline(x=50, line_color="#9ca3af")
    fig.add_trace(
        go.Scatter(
            x=[energy.solar_index],
            y=[energy.wind_index],
            mode="markers+text",
            text=[energy.label],
            textposition="top center",
            marker={"size": 18, "color": "#f59e0b", "line": {"color": "#111827", "width": 2}},
            name="This period",
            hovertemplate="Solar %{x:.0f}<br>Wind %{y:.0f}<extra>This period</extra>",
        )
    )
    annotations = [
        (25, 75, "low solar<br>high wind"),
        (75, 75, "high solar<br>high wind"),
        (25, 25, "low solar<br>low wind"),
        (75, 25, "high solar<br>low wind"),
    ]
    for x, y, text in annotations:
        fig.add_annotation(x=x, y=y, text=text, showarrow=False, font={"color": "#374151"})
    fig.update_layout(title="Interactive Solar-Wind Energy Quadrant", height=620, xaxis_title="Solar potential index", yaxis_title="Wind potential index")
    fig.update_xaxes(range=[0, 100])
    fig.update_yaxes(range=[0, 100])
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
    fig.update_layout(title="Hungary Electricity System · Rolling 72-Hour Context", height=820)
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
    fig.update_layout(title="Local Weather And National Electricity · Diagnostic Relationship", height=780)
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
        ("850-500 lapse", profile.diagnostics.get("lapse_rate_850_500_c_km"), " C/km"),
        ("Freezing level", profile.diagnostics.get("freezing_level_m_asl"), " m"),
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
    fig.update_layout(title=f"Interactive Skew-T Model Profile · Valid {valid}", height=820, hovermode="closest")
    return _save(fig, output)


def generate_all_figures(
    frame: pd.DataFrame,
    context_frame: pd.DataFrame,
    baseline: pd.DataFrame,
    anomalies: list[Anomaly],
    energy: EnergyIndex,
    electricity: pd.DataFrame,
    electricity_summary: ElectricitySummary,
    profile: ModelProfile,
    regime: RegimeClassification,
    current_start: date,
    output_dir: Path,
    config: AtlasConfig,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "meteogram": plot_meteogram(frame, output_dir / "meteogram.html", config),
        "seven_day_context": plot_seven_day_context(
            context_frame,
            current_start,
            output_dir / "seven_day_context.html",
            config,
        ),
        "wind_rose": plot_wind_rose(frame, output_dir / "wind_rose.html", config),
        "pressure_tendency": plot_pressure_tendency(frame, output_dir / "pressure_tendency.html", config),
        "dewpoint_spread": plot_dewpoint_spread(frame, output_dir / "dewpoint_spread.html", config),
        "solar_diurnal": plot_solar_diurnal(frame, baseline, output_dir / "solar_diurnal.html", config),
        "anomaly_bars": plot_anomaly_bars(anomalies, output_dir / "anomaly_bars.html"),
        "energy_quadrant": plot_energy_quadrant(energy, output_dir / "energy_quadrant.html"),
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
    }
