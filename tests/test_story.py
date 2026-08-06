import numpy as np
import pandas as pd

from atlas.anomalies import Anomaly
from atlas.climatology import ClimateReference
from atlas.energy import PhysicalEnergy
from atlas.fronts import FrontAnalysis
from atlas.hungaromet import LightningArchive, RadarArchive
from atlas.land import LandSurfaceAnalysis
from atlas.phenomena import PhenomenaAnalysis
from atlas.profile import ModelProfile
from atlas.regimes import RegimeClassification
from atlas.story import build_weather_story


def test_weather_story_links_weather_to_impacts():
    anomalies = [
        Anomaly("temperature_mean_c", "Temperature", 30.4, 23.7, 6.7, 2.6, 100, "deg C"),
        Anomaly("precipitation_total_mm", "Precipitation", 0, 6.1, -6.1, -0.8, 17, "mm"),
        Anomaly("cloud_cover_mean_pct", "Cloud", 6.4, 42.9, -36.5, -1.7, 3, "%"),
        Anomaly("shortwave_total_wh_m2", "Solar radiation", 20698, 16944, 3754, 1.5, 100, "Wh/m2"),
    ]
    climate = ClimateReference(
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        anomalies,
        anomalies,
        {item.metric: item.percentile for item in anomalies},
        [],
    )
    story = build_weather_story(
        regime=RegimeClassification(
            "Sunny high-pressure period",
            "Sunny high-pressure period with exceptional warmth and little cloud.",
            ["sunny"] * 3,
            ["above-normal radiation", "limited rainfall"],
        ),
        current_metrics={
            "temperature_mean_c": 30.4,
            "precipitation_total_mm": 0.0,
            "pressure_mean_hpa": 1015.5,
            "cloud_cover_mean_pct": 6.4,
        },
        anomalies=anomalies,
        climate=climate,
        fronts=FrontAnalysis([], pd.DataFrame(), []),
        phenomena=PhenomenaAnalysis([], []),
        profile=ModelProfile(
            pd.DataFrame(),
            None,
            "Open-Meteo",
            {"boundary_layer_height_m": 3160, "surface_based_cape_j_kg": 0},
            [],
        ),
        land=LandSurfaceAnalysis(
            pd.DataFrame(),
            pd.DataFrame(),
            {
                "water_balance_7d_mm": -47.8,
                "water_balance_30d_mm": -154.0,
                "vpd_max_kpa": 5.4,
            },
            {90: 3.3},
            "Exceptionally dry land-surface water balance",
            [],
        ),
        physical_energy=PhysicalEnergy(
            pd.DataFrame(), 18.16, 25.2, 5.02, 7.0, 86.3, None, None, []
        ),
        lightning=LightningArchive(pd.DataFrame(), pd.DataFrame(), []),
        radar=RadarArchive(
            [],
            np.array([]),
            np.array([]),
            np.empty((0, 0, 0)),
            np.empty((0, 0)),
            pd.DataFrame(),
            [],
        ),
        lightning_radius_km=150,
    )

    nodes = {node.id: node for node in story.nodes}
    edges = {(edge.source, edge.target) for edge in story.edges}
    assert len(nodes) == 9
    assert nodes["thermal"].label == "Exceptional warmth"
    assert nodes["sky"].label == "Exceptionally clear and dry"
    assert next(fact.value for fact in nodes["sky"].facts if fact.label == "Cloud rank") == "3rd percentile"
    assert nodes["pv"].label == "Strong PV weather yield"
    assert nodes["wind"].label == "Limited wind weather yield"
    assert nodes["land"].label == "Persistent land-surface deficit"
    assert ("sky", "pv") in edges
    assert ("thermal", "land") in edges
    assert ("regime", "wind") in edges
