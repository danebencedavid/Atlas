from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from datetime import timedelta
from pathlib import Path

import pandas as pd

from atlas.anomalies import anomalies_as_frame, baseline_metric_table, compute_anomalies, weekly_metrics
from atlas.baseline import fetch_baseline
from atlas.config import load_config
from atlas.dates import last_complete_week
from atlas.energy import compute_energy_index
from atlas.ingest import fetch_open_meteo_week
from atlas.plots import generate_all_figures
from atlas.quality import DataQualityReport, validate_hourly_week
from atlas.regimes import classify_week
from atlas.site import build_site
from atlas.site import archive_site


def parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def run_pipeline(
    config_path: str | Path = "configs/atlas.yml",
    week_start: date | None = None,
    today: date | None = None,
    refresh: bool = False,
) -> Path:
    config = load_config(config_path)
    quality_notes: list[str] = []
    if week_start is None:
        start, end = last_complete_week(today=today, tz_name=config.location.timezone)
        current: pd.DataFrame | None = None
        quality: DataQualityReport | None = None
        for lag in range(config.operations.max_week_lag + 1):
            candidate_start = start - timedelta(days=7 * lag)
            candidate_end = end - timedelta(days=7 * lag)
            try:
                candidate = fetch_open_meteo_week(config, candidate_start, candidate_end, refresh=refresh)
                candidate_quality = validate_hourly_week(
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
                        f"after the most recent week was incomplete."
                    )
                quality_notes.extend(candidate_quality.notes)
                break
            quality_notes.extend(f"{candidate_start.isoformat()} to {candidate_end.isoformat()}: {note}" for note in candidate_quality.notes)
        if current is None or quality is None:
            raise RuntimeError(
                f"No complete weekly weather archive found within {config.operations.max_week_lag} weeks. "
                f"Checks: {' | '.join(quality_notes)}"
            )
    else:
        start = week_start
        end = week_start + timedelta(days=6)
        current = fetch_open_meteo_week(config, start, end, refresh=refresh)
        quality = validate_hourly_week(
            current,
            start,
            end,
            config.location.timezone,
            minimum_coverage=config.operations.minimum_hourly_coverage,
        )
        quality_notes.extend(quality.notes)
        if not quality.ok:
            raise RuntimeError(f"Requested week failed data-quality checks: {' '.join(quality.notes)}")

    data_dir = config.outputs.data_dir
    processed_dir = data_dir / "processed"
    week_slug = f"{start.isoformat()}_{end.isoformat()}"
    archive_dir = config.outputs.reports_dir / "weeks" / week_slug
    figures_dir = archive_dir / "assets"
    processed_dir.mkdir(parents=True, exist_ok=True)

    baseline = fetch_baseline(config, start, end, refresh=refresh)

    current_metrics = weekly_metrics(current)
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
    regime = classify_week(current_with_local, anomalies)

    figure_paths = generate_all_figures(current, baseline, anomalies, energy, regime, figures_dir, config)

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
    weekly_metrics_path = processed_dir / "weekly_metrics.csv"
    baseline_metrics_path = processed_dir / "baseline_metrics.csv"
    anomalies_path = processed_dir / "anomalies.csv"
    current_hourly_path = processed_dir / "current_hourly.csv"
    summary_path = processed_dir / "summary.json"

    metrics_frame.to_csv(weekly_metrics_path, index=False)
    baseline_table.to_csv(baseline_metrics_path, index=False)
    anomalies_as_frame(anomalies).to_csv(anomalies_path, index=False)
    current.to_csv(current_hourly_path, index=False)
    summary_path.write_text(
        json.dumps(
            {
                "week_start": start.isoformat(),
                "week_end": end.isoformat(),
                "energy": asdict(energy),
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
        week_start=start.isoformat(),
        week_end=end.isoformat(),
        current_metrics=current_metrics,
        baseline_metrics=baseline_means,
        anomalies=anomalies,
        energy=energy,
        regime=regime,
        figure_paths=figure_paths,
        processed_paths={
            "weekly_metrics": weekly_metrics_path,
            "baseline_metrics": baseline_metrics_path,
            "anomalies": anomalies_path,
            "current_hourly": current_hourly_path,
            "summary": summary_path,
        },
        quality_notes=quality_notes,
    )
    archive_site(site_index.parent, archive_dir)
    return site_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Atlas weekly static weather dashboard.")
    parser.add_argument("--config", default="configs/atlas.yml", help="Path to Atlas YAML config.")
    parser.add_argument("--week-start", help="Explicit Monday week start date, YYYY-MM-DD.")
    parser.add_argument("--today", help="Override today's date for last-complete-week calculation, YYYY-MM-DD.")
    parser.add_argument("--refresh", action="store_true", help="Refetch API data instead of using cached raw responses.")
    args = parser.parse_args()

    output = run_pipeline(
        config_path=args.config,
        week_start=parse_date(args.week_start),
        today=parse_date(args.today),
        refresh=args.refresh,
    )
    print(f"Built Atlas site: {output}")


if __name__ == "__main__":
    main()
