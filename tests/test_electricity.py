from datetime import date

from atlas.config import AtlasConfig
from atlas.electricity import fetch_energy_charts, summarize_electricity


def test_energy_charts_ingestion_and_summary(tmp_path, monkeypatch):
    def fake_fetch(endpoint, _params, _cache_file, _refresh):
        timestamps = [1785196800, 1785200400, 1785204000]
        if endpoint == "public_power":
            return {
                "unix_seconds": timestamps,
                "production_types": [
                    {"name": "Load", "data": [5000, 5200, 5400]},
                    {"name": "Residual load", "data": [4300, 4200, 4100]},
                    {"name": "Solar", "data": [0, 600, 900]},
                    {"name": "Wind onshore", "data": [200, 250, 300]},
                    {"name": "Renewable share of load", "data": [10, 20, 30]},
                ],
            }
        if endpoint == "price":
            return {"unix_seconds": timestamps, "price": [70, 80, 90]}
        return {
            "unix_seconds": timestamps,
            "countries": [{"name": "Romania", "data": [0.1, 0.2, 0.3]}],
        }

    monkeypatch.setattr("atlas.electricity._fetch_endpoint", fake_fetch)
    result = fetch_energy_charts(
        AtlasConfig(),
        date(2026, 7, 27),
        date(2026, 7, 29),
        data_dir=tmp_path,
        refresh=True,
    )
    summary = summarize_electricity(result.frame)

    assert not result.frame.empty
    assert result.frame["load_mw"].tolist() == [5000, 5200, 5400]
    assert summary.available
    assert summary.average_load_mw == 5200
    assert summary.average_price_eur_mwh == 80
    assert summary.net_import_mean_mw == 200
    assert summary.solar_generation_mwh == 1500
