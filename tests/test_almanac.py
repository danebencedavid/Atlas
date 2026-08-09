from datetime import date

import pandas as pd
import pytest

from atlas.almanac import build_almanac
from atlas.config import AtlasConfig


def _archive(first_year: int, final_year: int) -> pd.DataFrame:
    dates = pd.date_range(f"{first_year}-01-01", f"{final_year}-12-31", freq="D")
    return pd.DataFrame(
        {
            "date": dates.date,
            "temperature_2m_mean": 10.0,
            "precipitation_sum": 1.0,
            "wind_speed_100m_mean": 4.0,
            "pressure_msl_mean": 1013.0,
            "cloud_cover_mean": 50.0,
            "shortwave_radiation_sum": 5.0,
            "et0_fao_evapotranspiration_sum": 1.0,
        }
    )


def test_build_almanac_produces_twelve_months_and_four_seasons():
    archive = _archive(2000, 2002)

    almanac = build_almanac(archive, AtlasConfig())

    assert almanac.archive_start_year == 2000
    assert almanac.archive_end_year == 2002
    assert [m.name for m in almanac.months] == [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    assert {s.name for s in almanac.seasons} == {"Winter", "Spring", "Summer", "Autumn"}
    assert all(m.years == 3 for m in almanac.months)


def test_build_almanac_identifies_calendar_extremes():
    archive = _archive(2010, 2012)
    archive.loc[archive["date"] == date(2011, 8, 15), "temperature_2m_mean"] = 38.4
    archive.loc[archive["date"] == date(2010, 1, 20), "temperature_2m_mean"] = -18.2
    archive.loc[archive["date"] == date(2012, 6, 3), "precipitation_sum"] = 64.0

    almanac = build_almanac(archive, AtlasConfig())

    warmest = next(r for r in almanac.all_time_records if r.label.startswith("Warmest day"))
    coldest = next(r for r in almanac.all_time_records if r.label.startswith("Coldest day"))
    wettest = next(r for r in almanac.all_time_records if r.label.startswith("Wettest day"))
    assert warmest.on_date == "2011-08-15"
    assert warmest.value == 38.4
    assert coldest.on_date == "2010-01-20"
    assert wettest.on_date == "2012-06-03"
    assert wettest.value == 64.0

    august = next(m for m in almanac.months if m.name == "August")
    assert august.warmest_day is not None
    assert august.warmest_day.on_date == "2011-08-15"

    summer = next(s for s in almanac.seasons if s.name == "Summer")
    assert summer.warmest_day is not None
    assert summer.warmest_day.on_date == "2011-08-15"


def test_build_almanac_groups_december_into_the_following_winter():
    archive = _archive(2015, 2017)
    archive.loc[archive["date"] == date(2016, 12, 25), "temperature_2m_mean"] = -12.0

    almanac = build_almanac(archive, AtlasConfig())

    winter = next(s for s in almanac.seasons if s.name == "Winter")
    assert winter.coldest_day is not None
    assert winter.coldest_day.on_date == "2016-12-25"


def test_build_almanac_rejects_empty_archive():
    with pytest.raises(ValueError):
        build_almanac(pd.DataFrame(), AtlasConfig())
