import json
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from atlas.anomalies import Anomaly
from atlas.climatology import ClimateReference
from atlas.config import AtlasConfig
from atlas.hungaromet import LightningArchive, RadarArchive
from atlas.land import analyze_land_surface
from atlas.phenomena import PhenomenaAnalysis, WeatherPhenomenon
from atlas.plots import (
    plot_climate_reference,
    plot_land_surface,
    plot_phenomena_timeline,
    plot_satellite_diary,
    plot_synoptic_evolution,
)
from atlas.satellite import SatelliteArchive, SatelliteFrame
from atlas.site import _thin_published_satellite_media
from atlas.synoptic import SynopticArchive


def _anomaly(metric: str, label: str, z_score: float, percentile: float) -> Anomaly:
    return Anomaly(metric, label, 1.0, 0.0, 1.0, z_score, percentile, "test")


def test_new_scientific_visuals_render(tmp_path: Path):
    config = AtlasConfig()
    standard = [
        _anomaly("temperature_mean_c", "Temperature", 1.2, 88.0),
        _anomaly("precipitation_total_mm", "Precipitation", -0.8, 22.0),
    ]
    recent = [
        _anomaly("temperature_mean_c", "Temperature", 0.7, 74.0),
        _anomaly("precipitation_total_mm", "Precipitation", -0.4, 35.0),
    ]
    climate = ClimateReference(
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        standard,
        recent,
        {"temperature_mean_c": 91.0, "precipitation_total_mm": 18.0},
        ["Synthetic reference fixture."],
    )
    climate_path = plot_climate_reference(climate, tmp_path / "climate.html")

    times = pd.date_range("2026-07-01", periods=96, freq="h", tz="UTC")
    hour = np.arange(len(times), dtype=float)
    land_frame = pd.DataFrame(
        {
            "time": times,
            "precipitation": np.where(hour % 37 == 0, 3.0, 0.0),
            "et0_fao_evapotranspiration": np.maximum(0.0, np.sin(hour / 6.0)) * 0.2,
            "vapour_pressure_deficit": 0.6 + np.maximum(0.0, np.sin(hour / 5.0)),
            "soil_temperature_0_to_7cm": 20.0 + np.sin(hour / 8.0),
            "soil_temperature_7_to_28cm": 18.0 + np.sin(hour / 12.0),
            "soil_temperature_28_to_100cm": 16.0 + np.sin(hour / 20.0),
            "soil_temperature_100_to_255cm": 14.0 + np.sin(hour / 30.0),
            "soil_moisture_0_to_7cm": 0.19 + np.sin(hour / 18.0) * 0.01,
            "soil_moisture_7_to_28cm": 0.22 + np.sin(hour / 24.0) * 0.01,
            "soil_moisture_28_to_100cm": 0.25 + np.sin(hour / 30.0) * 0.01,
            "soil_moisture_100_to_255cm": 0.28 + np.sin(hour / 36.0) * 0.01,
        }
    )
    samples = {days: pd.Series(np.linspace(-30, 30, 30)) for days in (7, 30, 90)}
    land = analyze_land_surface(land_frame, samples)
    land_path = plot_land_surface(land, tmp_path / "land.html", config)

    phenomena = PhenomenaAnalysis(
        [
            WeatherPhenomenon(
                times[5], times[8], "Fog", "Visibility reached 600 m.", 0.92, "Station"
            ),
            WeatherPhenomenon(
                times[30], times[33], "Thunderstorm", "Radar and LINET concurrence.", 0.96, "Radar + LINET"
            ),
        ],
        ["Synthetic phenomenon fixture."],
    )
    phenomena_path = plot_phenomena_timeline(
        phenomena, tmp_path / "phenomena.html", config
    )

    for name, color in (("airmass.png", (72, 94, 130)), ("infrared.png", (165, 72, 52))):
        Image.new("RGB", (640, 400), color).save(tmp_path / name)
    satellite = SatelliteArchive(
        {
            "AirmassRGB": [SatelliteFrame(times[10], "AirmassRGB", tmp_path / "airmass.png")],
            "InfraCloud": [SatelliteFrame(times[30], "InfraCloud", tmp_path / "infrared.png")],
        },
        ["Synthetic satellite fixture."],
    )
    radar = RadarArchive(
        [],
        np.array([]),
        np.array([]),
        np.empty((0, 0, 0)),
        np.empty((0, 0)),
        pd.DataFrame(
            {
                "time": [times[10], times[30]],
                "domain_max_dbz": [28.0, 52.0],
                "reflectivity_dbz": [5.0, 34.0],
            }
        ),
        ["Synthetic radar fixture."],
    )
    lightning = LightningArchive(
        pd.DataFrame(),
        pd.DataFrame({"time": [times[10], times[30]], "flash_count": [0, 14]}),
        ["Synthetic lightning fixture."],
    )
    satellite_path = plot_satellite_diary(
        satellite, radar, lightning, tmp_path / "satellite.html", config
    )

    latitudes = np.linspace(43.0, 52.0, 5)
    longitudes = np.linspace(14.0, 28.0, 6)
    longitude_grid, latitude_grid = np.meshgrid(longitudes, latitudes)
    shape = (2, len(latitudes), len(longitudes))
    base = np.broadcast_to(latitude_grid + longitude_grid, shape).copy()
    synoptic = SynopticArchive(
        times=[times[0], times[6]],
        latitudes=latitudes,
        longitudes=longitudes,
        pressure_msl_hpa=1000.0 + base,
        height_500m=5450.0 + base * 4.0,
        height_300m=9050.0 + base * 5.0,
        temperature_850c=base - 55.0,
        wind_u_850ms=np.full(shape, 6.0),
        wind_v_850ms=np.full(shape, 3.0),
        wind_speed_300ms=25.0 + base / 3.0,
        vorticity_500_1e5_s=base - base.mean(),
        relative_humidity_700pct=40.0 + base / 2.0,
        vertical_velocity_700ms=(base - base.mean()) / 100.0,
        theta_e_850k=300.0 + base / 2.0,
        temperature_advection_850c_3h=(base - base.mean()) / 3.0,
        frontogenesis_850k_100km_3h=np.abs(base - base.mean()) / 4.0,
        notes=["Synthetic synoptic fixture."],
    )
    synoptic_path = plot_synoptic_evolution(
        synoptic, tmp_path / "synoptic.html", config
    )

    for path in (
        climate_path,
        land_path,
        phenomena_path,
        satellite_path,
        synoptic_path,
    ):
        assert path.exists()
        assert path.stat().st_size > 1_000
        figure_html = path.read_text(encoding="utf-8")
        assert 'class="atlas-figure-attribution"' in figure_html
        assert "font:11px/1.55" in figure_html
        assert "Weather data from" in figure_html
        assert "Forrás:" in figure_html
        assert "HungaroMet Nonprofit Zrt." in figure_html
        assert 'href="https://www.met.hu/"' in figure_html
        assert "Atlas modifies HungaroMet source data" in figure_html
        assert "kizárólag saját felelősségére" in figure_html
        assert "nem vállal felelősséget" in figure_html
        assert "Energy-Charts, Fraunhofer ISE" in figure_html
        assert (
            "Neither the European Commission nor ECMWF is responsible" in figure_html
        )
    assert (tmp_path / "satellite_media").is_dir()
    satellite_html = satellite_path.read_text(encoding="utf-8")
    assert "AirmassRGB" in satellite_html
    assert 'id="zoom-in"' in satellite_html
    synoptic_html = synoptic_path.read_text(encoding="utf-8")
    assert "850 hPa theta-e" in synoptic_html
    assert "850 hPa frontogenesis" in synoptic_html


def test_published_archive_satellite_thinning_keeps_the_player_consistent(
    tmp_path: Path,
) -> None:
    """Thinning the deployable copy must not leave the frame player broken.

    Satellite media is the largest single term in published archive growth, so
    the archive copy steps through time more coarsely than the capture. The
    frozen source edition and the verified cold package keep every frame, so the
    only correctness requirement here is that the published page and the files
    beside it still agree, and that the reduction is disclosed on the page.
    """

    config = AtlasConfig()
    times = pd.date_range("2026-10-13T00:00Z", periods=24, freq="1h")
    for name in ("airmass.png", "infrared.png"):
        Image.new("RGB", (320, 200), (90, 110, 140)).save(tmp_path / name)
    satellite = SatelliteArchive(
        {
            "AirmassRGB": [
                SatelliteFrame(moment, "AirmassRGB", tmp_path / "airmass.png")
                for moment in times
            ],
            "InfraCloud": [
                SatelliteFrame(moment, "InfraCloud", tmp_path / "infrared.png")
                for moment in times
            ],
        },
        ["Synthetic satellite fixture."],
    )
    radar = RadarArchive(
        [],
        np.array([]),
        np.array([]),
        np.empty((0, 0, 0)),
        np.empty((0, 0)),
        pd.DataFrame(),
        ["Synthetic radar fixture."],
    )
    lightning = LightningArchive(pd.DataFrame(), pd.DataFrame(), ["No strikes."])

    edition = tmp_path / "edition"
    assets = edition / "assets"
    assets.mkdir(parents=True)
    plot_satellite_diary(
        satellite, radar, lightning, assets / "satellite_diary.html", config
    )
    media = assets / "satellite_media"
    captured = sorted(path.name for path in media.iterdir())
    assert len(captured) == 48

    removed = _thin_published_satellite_media(edition, 360)

    assert removed > 0
    document = (assets / "satellite_diary.html").read_text(encoding="utf-8")
    start = document.index("const data=") + len("const data=")
    payload = json.loads(document[start : document.index("; const product=")])
    published = {
        PurePosixPath(frame["src"]).name
        for frames in payload["products"].values()
        for frame in frames
    }
    remaining = {path.name for path in media.iterdir()}

    # Nothing the page asks for is missing, and nothing unreferenced is shipped.
    assert published == remaining
    assert published < set(captured)
    for frames in payload["products"].values():
        steps = [
            pd.Timestamp(right["time"]) - pd.Timestamp(left["time"])
            for left, right in zip(frames, frames[1:])
        ]
        # Every step but the last respects the cadence. The last may be shorter:
        # the final captured frame is kept deliberately so the player still
        # reaches the end of the period instead of stopping short of it.
        assert all(step >= pd.Timedelta(minutes=360) for step in steps[:-1])
        assert frames[-1]["time"] == times[-1].isoformat()
    assert "Published archive copy:" in document

    # Rebuilding the published archive runs this over every online edition, so a
    # second pass has to be a no-op rather than thinning what it already thinned.
    assert _thin_published_satellite_media(edition, 360) == 0


def test_satellite_thinning_rejects_a_diverged_plot_template(tmp_path: Path) -> None:
    edition = tmp_path / "edition"
    assets = edition / "assets"
    (assets / "satellite_media").mkdir(parents=True)
    (assets / "satellite_media" / "AirmassRGB_20261013_0000.webp").write_bytes(b"frame")
    (assets / "satellite_diary.html").write_text(
        "<html><body>no payload here</body></html>", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="no recognizable frame payload"):
        _thin_published_satellite_media(edition, 360)
