from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from datetime import timedelta
from pathlib import Path

import pandas as pd

from atlas.anomalies import anomalies_as_frame, baseline_metric_table, compute_anomalies, period_metrics
from atlas.baseline import fetch_baseline
from atlas.config import load_config
from atlas.dates import last_complete_period
from atlas.electricity import fetch_energy_charts, summarize_electricity
from atlas.energy import compute_energy_index
from atlas.ingest import fetch_open_meteo_period
from atlas.plots import generate_all_figures
from atlas.profile import fetch_model_profile
from atlas.quality import DataQualityReport, validate_hourly_period
from atlas.regimes import classify_period
from atlas.site import build_site
from atlas.site import archive_site


def parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def run_pipeline(
    config_path: str | Path = "configs/atlas.yml",
    period_start: date | None = None,
    today: date | None = None,
    refresh: bool = False,
) -> Path:
    config = load_config(config_path)
    quality_notes: list[str] = []
    if period_start is None:
        start, end = last_complete_period(
            today=today,
            tz_name=config.location.timezone,
            days=config.reporting.window_days,
        )
        current: pd.DataFrame | None = None
        quality: DataQualityReport | None = None
        for lag in range(config.operations.max_period_lag_days + 1):
            candidate_start = start - timedelta(days=lag)
            candidate_end = end - timedelta(days=lag)
            try:
                candidate = fetch_open_meteo_period(config, candidate_start, candidate_end, refresh=refresh)
                candidate_quality = validate_hourly_period(
                    candidate,
                    candidate_start,
                    candidate_end,
                    config.location.timezone,
                    minimum_coverage=config.operations.minimum_hourly_coverage,
                )
            except Exception as exc:
                quality_notes.append(f"{candidate_start.isoformat()} to {candidate_end.isoformat()} was unavailable: {exc}")
                continue
            if candidate_quality.ok:
                start, end = candidate_start, candidate_end
                current = candidate
                quality = candidate_quality
                if lag:
                    quality_notes.append(
                        f"Archive lag fallback used: selected {start.isoformat()} to {end.isoformat()} "
                        f"after the most recent rolling period was incomplete."
                    )
                quality_notes.extend(candidate_quality.notes)
                break
            quality_notes.extend(f"{candidate_start.isoformat()} to {candidate_end.isoformat()}: {note}" for note in candidate_quality.notes)
        if current is None or quality is None:
            raise RuntimeError(
                f"No complete weather archive found within {config.operations.max_period_lag_days} days. "
                f"Checks: {' | '.join(quality_notes)}"
            )
    else:
        start = period_start
        end = period_start + timedelta(days=config.reporting.window_days - 1)
        current = fetch_open_meteo_period(config, start, end, refresh=refresh)
        quality = validate_hourly_period(
            current,
            start,
            end,
            config.location.timezone,
            minimum_coverage=config.operations.minimum_hourly_coverage,
        )
        quality_notes.extend(quality.notes)
        if not quality.ok:
            raise RuntimeError(f"Requested period failed data-quality checks: {' '.join(quality.notes)}")

    data_dir = config.outputs.data_dir
    processed_dir = data_dir / "processed"
    period_slug = f"{start.isoformat()}_{end.isoformat()}"
    archive_dir = config.outputs.reports_dir / "periods" / period_slug
    figures_dir = archive_dir / "assets"
    processed_dir.mkdir(parents=True, exist_ok=True)

    context_start = end - timedelta(days=config.reporting.context_days - 1)
    try:
        context = fetch_open_meteo_period(config, context_start, end, refresh=refresh)
        context_quality = validate_hourly_period(
            context,
            context_start,
            end,
            config.location.timezone,
            minimum_coverage=config.operations.minimum_hourly_coverage,
        )
        if not context_quality.ok:
            raise RuntimeError(" ".join(context_quality.notes))
    except Exception as exc:
        context = current.copy()
        quality_notes.append(f"Seven-day context was unavailable; the current period is shown instead: {exc}")

    baseline = fetch_baseline(config, start, end, refresh=refresh)
    electricity_data = fetch_energy_charts(config, start, end, refresh=refresh)
    electricity_summary = summarize_electricity(electricity_data.frame)
    model_profile = fetch_model_profile(config, end, refresh=refresh)

    current_metrics = period_metrics(current)
    baseline_table = baseline_metric_table(baseline)
    baseline_means = {
        column: float(pd.to_numeric(baseline_table[column], errors="coerce").mean())
        for column in baseline_table.columns
        if column != "baseline_year"
    }
    anomalies = compute_anomalies(current_metrics, baseline_table)
    energy = compute_energy_index(current_metrics, baseline_means)

    current_with_local = current.copy()
    current_with_local["local_time"] = pd.to_datetime(current_with_local["time"], utc=True).dt.tz_convert(config.location.timezone)
    regime = classify_period(current_with_local, anomalies)

    figure_paths = generate_all_figures(
        frame=current,
        context_frame=context,
        baseline=baseline,
        anomalies=anomalies,
        energy=energy,
        electricity=electricity_data.frame,
        electricity_summary=electricity_summary,
        profile=model_profile,
        regime=regime,
        current_start=start,
        output_dir=figures_dir,
        config=config,
    )

    metrics_frame = pd.DataFrame(
        [
            {"metric": key, "value": value, "scope": "current"}
            for key, value in current_metrics.items()
        ]
        + [
            {"metric": key, "value": value, "scope": "baseline_mean"}
            for key, value in baseline_means.items()
        ]
    )
    period_metrics_path = processed_dir / "period_metrics.csv"
    baseline_metrics_path = processed_dir / "baseline_metrics.csv"
    anomalies_path = processed_dir / "anomalies.csv"
    current_hourly_path = processed_dir / "current_hourly.csv"
    context_hourly_path = processed_dir / "seven_day_context_hourly.csv"
    electricity_path = processed_dir / "electricity.csv"
    model_profile_path = processed_dir / "model_profile.csv"
    summary_path = processed_dir / "summary.json"

    metrics_frame.to_csv(period_metrics_path, index=False)
    baseline_table.to_csv(baseline_metrics_path, index=False)
    anomalies_as_frame(anomalies).to_csv(anomalies_path, index=False)
    current.to_csv(current_hourly_path, index=False)
    context.to_csv(context_hourly_path, index=False)
    electricity_data.frame.to_csv(electricity_path, index=False)
    model_profile.frame.to_csv(model_profile_path, index=False)
    summary_path.write_text(
        json.dumps(
            {
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "context_start": context_start.isoformat(),
                "context_end": end.isoformat(),
                "energy": asdict(energy),
                "electricity": asdict(electricity_summary),
                "electricity_notes": electricity_data.notes,
                "model_profile": {
                    "valid_time": (
                        model_profile.valid_time.isoformat()
                        if model_profile.valid_time is not None
                        else None
                    ),
                    "source": model_profile.source,
                    "diagnostics": model_profile.diagnostics,
                    "notes": model_profile.notes,
                },
                "regime": asdict(regime),
                "current_metrics": current_metrics,
                "baseline_metrics": baseline_means,
                "data_quality": asdict(quality),
                "quality_notes": quality_notes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    site_index = build_site(
        config=config,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        current_metrics=current_metrics,
        baseline_metrics=baseline_means,
        anomalies=anomalies,
        energy=energy,
        electricity=electricity_summary,
        electricity_notes=electricity_data.notes,
        profile=model_profile,
        regime=regime,
        figure_paths=figure_paths,
        processed_paths={
            "period_metrics": period_metrics_path,
            "baseline_metrics": baseline_metrics_path,
            "anomalies": anomalies_path,
            "current_hourly": current_hourly_path,
            "seven_day_context": context_hourly_path,
            "electricity": electricity_path,
            "model_profile": model_profile_path,
            "summary": summary_path,
        },
        quality_notes=quality_notes,
    )
    archive_site(site_index.parent, archive_dir)
    return site_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Atlas rolling three-day static weather dashboard.")
    parser.add_argument("--config", default="configs/atlas.yml", help="Path to Atlas YAML config.")
    parser.add_argument(
        "--period-start",
        "--week-start",
        dest="period_start",
        help="Explicit reporting-period start date, YYYY-MM-DD.",
    )
    parser.add_argument("--today", help="Override today's date for last-complete-period calculation, YYYY-MM-DD.")
    parser.add_argument("--refresh", action="store_true", help="Refetch API data instead of using cached raw responses.")
    args = parser.parse_args()

    output = run_pipeline(
        config_path=args.config,
        period_start=parse_date(args.period_start),
        today=parse_date(args.today),
        refresh=args.refresh,
    )
    print(f"Built Atlas site: {output}")


if __name__ == "__main__":
    main()
