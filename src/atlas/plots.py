from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from atlas.anomalies import Anomaly
from atlas.config import AtlasConfig
from atlas.energy import EnergyIndex
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
    fig.update_layout(title="Weekly Interactive Meteogram", height=980)
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
        f"{item.label}<br>This week: {item.value:.1f} {item.unit}<br>Baseline: {item.baseline_mean:.1f} {item.unit}<br>Anomaly: {item.anomaly:+.1f} {item.unit}<br>Percentile: {item.percentile:.0f}"
        for item in anomalies
    ]
    colors = ["#dc2626" if value > 0 else "#2563eb" for value in z_scores]
    fig = go.Figure(go.Bar(x=labels, y=z_scores, marker={"color": colors}, text=[f"{value:+.1f}" for value in z_scores], hovertext=hover, hoverinfo="text"))
    fig.add_hline(y=0, line_color="#71717a")
    fig.update_layout(title="Interactive Weekly Anomalies Versus Baseline", height=520, yaxis_title="standard deviations from normal")
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
            name="This week",
            hovertemplate="Solar %{x:.0f}<br>Wind %{y:.0f}<extra>This week</extra>",
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


def plot_regime_strip(regime: RegimeClassification, output: Path) -> Path:
    colors = {
        "sunny": "#facc15",
        "stagnant": "#94a3b8",
        "frontal": "#38bdf8",
        "hot": "#ef4444",
        "frost": "#93c5fd",
        "mixed": "#a7f3d0",
    }
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    values = regime.daily_labels[:7]
    while len(values) < 7:
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


def generate_all_figures(
    frame: pd.DataFrame,
    baseline: pd.DataFrame,
    anomalies: list[Anomaly],
    energy: EnergyIndex,
    regime: RegimeClassification,
    output_dir: Path,
    config: AtlasConfig,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "meteogram": plot_meteogram(frame, output_dir / "meteogram.html", config),
        "wind_rose": plot_wind_rose(frame, output_dir / "wind_rose.html", config),
        "pressure_tendency": plot_pressure_tendency(frame, output_dir / "pressure_tendency.html", config),
        "dewpoint_spread": plot_dewpoint_spread(frame, output_dir / "dewpoint_spread.html", config),
        "solar_diurnal": plot_solar_diurnal(frame, baseline, output_dir / "solar_diurnal.html", config),
        "anomaly_bars": plot_anomaly_bars(anomalies, output_dir / "anomaly_bars.html"),
        "energy_quadrant": plot_energy_quadrant(energy, output_dir / "energy_quadrant.html"),
        "regime_strip": plot_regime_strip(regime, output_dir / "regime_strip.html"),
    }
