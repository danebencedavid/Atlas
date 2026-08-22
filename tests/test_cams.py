from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from atlas.cams import (
    IRRADIANCE_CAVEAT,
    SNOW_CAVEAT,
    CamsCredentialError,
    fetch_cams_radiation,
    parse_cams_csv,
    read_token,
)
from atlas.config import AtlasConfig, CamsConfig, OutputConfig

# Shaped like a real CAMS export: commented preamble, semicolon separated, and an
# ISO interval in the period column.
EXPORT = """# Coding: utf-8
# Title: CAMS solar radiation time-series
# Latitude (positive North) ; Longitude (positive East)
# 47.5316;21.6273
# Observation period;TOA;Clear sky GHI;Clear sky BHI;Clear sky DHI;Clear sky BNI;GHI;BHI;DHI;BNI;Reliability
2024-06-01T00:00:00.0/2024-06-01T01:00:00.0;0.0;0.0;0.0;0.0;0.0;0.0;0.0;0.0;0.0;1.0
2024-06-01T10:00:00.0/2024-06-01T11:00:00.0;900.1;700.5;600.2;100.3;800.4;650.0;540.0;110.0;700.0;1.0
2024-06-01T11:00:00.0/2024-06-01T12:00:00.0;950.0;780.0;660.0;120.0;820.0;300.0;120.0;180.0;200.0;1.0
"""


def _config(tmp_path: Path, **overrides) -> AtlasConfig:
    return AtlasConfig(
        cams=CamsConfig(chunk_days=31, **overrides),
        outputs=OutputConfig(data_dir=tmp_path / "data"),
    )


def test_missing_token_explains_how_to_supply_one(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.delenv(config.cams.token_env_var, raising=False)
    with pytest.raises(CamsCredentialError) as error:
        read_token(config)
    message = str(error.value)
    # Actionable rather than a stack trace, and it names the variable.
    assert config.cams.token_env_var in message
    assert "ads.atmosphere.copernicus.eu" in message
    assert "never written into this repository" in message


def test_token_is_read_from_the_environment(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setenv(config.cams.token_env_var, "  secret-token  ")
    assert read_token(config) == "secret-token"


def test_export_parses_into_hourly_utc_irradiance():
    frame = parse_cams_csv(EXPORT)
    assert list(frame.columns) == ["time", "shortwave_radiation", "direct_radiation", "diffuse_radiation"]
    assert len(frame) == 3
    # The interval end is the valid hour, and everything internal is UTC.
    assert str(frame["time"].dt.tz) == "UTC"
    assert frame["time"].iloc[1] == pd.Timestamp("2024-06-01T11:00:00Z")
    # GHI, BHI and DHI map to the archive's shortwave, direct and diffuse.
    assert frame["shortwave_radiation"].iloc[1] == pytest.approx(650.0)
    assert frame["direct_radiation"].iloc[1] == pytest.approx(540.0)
    assert frame["diffuse_radiation"].iloc[1] == pytest.approx(110.0)


# Two rows, one hour apart, with values that cannot be confused for each other.
# The whole point is that a one-hour error here is invisible in every aggregate
# the report prints, so it has to be pinned at the parser.
INTERVAL_PIN = """# Observation period;TOA;Clear sky GHI;Clear sky BHI;Clear sky DHI;Clear sky BNI;GHI;BHI;DHI;BNI;Reliability
2024-06-01T04:00:00.0/2024-06-01T05:00:00.0;362.8;219.4;150.4;69.0;539.3;111.0;222.0;333.0;444.0;1.0
2024-06-01T05:00:00.0/2024-06-01T06:00:00.0;576.8;393.4;300.7;92.7;687.1;555.0;666.0;777.0;888.0;1.0
"""


def test_the_valid_time_is_the_interval_end_not_its_start():
    """CAMS integrates over [start, end) and labels the row by start.

    Open-Meteo labels hourly radiation by the end of the hour it averages over,
    as the preceding-hour mean. Reading the start therefore put every irradiance
    pair one hour out of step: it inflated shortwave MAE at 24 h from 32 to 55
    W/m^2, and left a clean one-hour shift in the residual for any correction to
    find and remove, which would have read as skill. Nothing in a seasonal or
    diurnal average reveals a uniform shift, so this is pinned here or nowhere.
    """
    frame = parse_cams_csv(INTERVAL_PIN)
    assert len(frame) == 2
    # 05:00, the end of the 04:00-05:00 integration, not 04:00.
    assert frame["time"].iloc[0] == pd.Timestamp("2024-06-01T05:00:00Z")
    assert frame["time"].iloc[1] == pd.Timestamp("2024-06-01T06:00:00Z")
    # The values must travel with their own interval, not slide onto the next.
    assert frame["shortwave_radiation"].iloc[0] == pytest.approx(111.0)
    assert frame["shortwave_radiation"].iloc[1] == pytest.approx(555.0)


def test_a_malformed_export_is_rejected_rather_than_half_parsed():
    with pytest.raises(ValueError, match="observation-period header"):
        parse_cams_csv("just some text\nwithout a header\n")


def test_cached_responses_need_no_token_at_all(tmp_path, monkeypatch):
    """A fully cached run must not require a credential, so iteration is free."""
    config = _config(tmp_path)
    cache = tmp_path / "data" / "raw" / "cams" / "cams_radiation_2024-06-01_2024-06-30.csv"
    cache.parent.mkdir(parents=True)
    cache.write_text(EXPORT, encoding="utf-8")
    monkeypatch.delenv(config.cams.token_env_var, raising=False)

    def explode(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("a cached window must not call the API")

    monkeypatch.setattr("atlas.cams._submit", explode)
    result = fetch_cams_radiation(config, date(2024, 6, 1), date(2024, 6, 30))
    assert result.available
    assert len(result.frame) == 3


def test_notes_carry_attribution_and_the_snow_caveat(tmp_path, monkeypatch):
    config = _config(tmp_path)
    cache = tmp_path / "data" / "raw" / "cams" / "cams_radiation_2024-06-01_2024-06-30.csv"
    cache.parent.mkdir(parents=True)
    cache.write_text(EXPORT, encoding="utf-8")
    result = fetch_cams_radiation(config, date(2024, 6, 1), date(2024, 6, 30))
    joined = " ".join(result.notes)
    assert "CC BY 4.0" in joined
    assert "snow cover" in joined
    assert SNOW_CAVEAT in result.notes


def test_the_label_says_satellite_derived_not_observation():
    # "observation" would overstate a satellite retrieval.
    assert "satellite-derived" in IRRADIANCE_CAVEAT
    assert "not ground measurement" in IRRADIANCE_CAVEAT


def test_disabled_ingestion_returns_nothing_without_calling_out(tmp_path):
    config = _config(tmp_path, enabled=False)
    result = fetch_cams_radiation(config, date(2024, 6, 1), date(2024, 6, 30))
    assert not result.available
    assert result.notes == ["CAMS ingestion is disabled."]
