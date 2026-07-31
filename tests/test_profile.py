from datetime import date

from atlas.config import AtlasConfig, ProfileConfig
from atlas.profile import fetch_model_profile


def test_model_profile_selects_target_hour_and_computes_diagnostics(tmp_path, monkeypatch):
    levels = [1000, 925, 850, 700, 500]
    times = [f"2026-07-29T{hour:02d}:00" for hour in range(24)]
    hourly = {"time": times}
    temperatures = {1000: 25, 925: 20, 850: 15, 700: 3, 500: -13}
    heights = {1000: 100, 925: 760, 850: 1500, 700: 3100, 500: 5700}
    for level in levels:
        hourly[f"temperature_{level}hPa"] = [temperatures[level]] * 24
        hourly[f"relative_humidity_{level}hPa"] = [60] * 24
        hourly[f"wind_speed_{level}hPa"] = [5 + level / 1000] * 24
        hourly[f"wind_direction_{level}hPa"] = [220] * 24
        hourly[f"geopotential_height_{level}hPa"] = [heights[level]] * 24

    monkeypatch.setattr("atlas.profile.fetch_json_with_retry", lambda _url, _params: {"hourly": hourly})
    config = AtlasConfig(profile=ProfileConfig(pressure_levels_hpa=levels, target_hour_utc=12))

    profile = fetch_model_profile(config, date(2026, 7, 29), data_dir=tmp_path, refresh=True)

    assert len(profile.frame) == 5
    assert profile.valid_time.hour == 12
    assert profile.diagnostics["lapse_rate_850_500_c_km"] > 6
    assert profile.frame["dew_point_c"].notna().all()
    assert len(profile.series) == 24 * len(levels)
    assert profile.series["time"].nunique() == 24
    assert len(profile.surface_series) == 24
