from atlas.energy import compute_energy_index


def test_energy_index_clips_and_labels_solar_favored_week():
    current = {
        "shortwave_total_wh_m2": 6000.0,
        "cloud_cover_mean_pct": 30.0,
        "wind_speed_mean_ms": 2.0,
    }
    baseline = {
        "shortwave_total_wh_m2": 5000.0,
        "cloud_cover_mean_pct": 45.0,
        "wind_speed_mean_ms": 4.0,
    }

    result = compute_energy_index(current, baseline)

    assert result.solar_index == 100.0
    assert result.wind_index < 50.0
    assert result.label == "solar-favored"


def test_invalid_solar_baseline_marks_numeric_fallback_as_invalid_evidence():
    current = {"shortwave_total_wh_m2": 5000, "cloud_cover_mean_pct": 30, "wind_speed_mean_ms": 3}
    result = compute_energy_index(current, dict(current, shortwave_total_wh_m2=float("nan")))
    assert result.solar_index == 50
    assert result.solar_evidence["status"] == "fallback"
