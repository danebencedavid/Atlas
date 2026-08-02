import pandas as pd

from atlas.land import analyze_land_surface


def test_land_surface_uses_standard_water_balance_percentile():
    # 22 UTC is local midnight in Debrecen during summer time.
    times = pd.date_range("2026-04-30 22:00", periods=90 * 24, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "time": times,
            "precipitation": 0.0,
            "et0_fao_evapotranspiration": 0.1,
            "vapour_pressure_deficit": 1.4,
            "soil_temperature_0_to_7cm": 24.0,
            "soil_temperature_7_to_28cm": 20.0,
            "soil_temperature_28_to_100cm": 16.0,
            "soil_temperature_100_to_255cm": 13.0,
            "soil_moisture_0_to_7cm": 0.12,
            "soil_moisture_7_to_28cm": 0.16,
            "soil_moisture_28_to_100cm": 0.2,
            "soil_moisture_100_to_255cm": 0.23,
        }
    )
    samples = {days: pd.Series([-100.0, -50.0, -20.0, 0.0]) for days in (7, 30, 90)}

    analysis = analyze_land_surface(frame, samples)

    assert round(analysis.metrics["water_balance_90d_mm"], 1) == -216.0
    assert analysis.water_balance_percentiles[90] == 0.0
    assert "Exceptionally dry" in analysis.moisture_context
