"""Run dbt on a tiny bronze fixture (small real responses, one per source) and check values."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "tests" / "samples"
DBT = Path(sys.executable).with_name("dbt.exe" if os.name == "nt" else "dbt")

# source -> (sample file, bronze file name, manifest params)
FIXTURE = {
    "pihps": ("pihps_grid_jakarta_cabai_rawit.json", "traditional_c34_20261013_20261024.json",
              {"market_tier": "traditional", "city_id": 34}),
    "bps": ("bps_cpi_food_2025_trimmed.json", "var2212_y2025.json",
            {"var_id": 2212, "year": 2025, "measure": "index", "base_year": 2022,
             "level": "city", "th": 125}),
    "weather": ("weather_jakarta_10d.json", "p31_20261015_20261024.json",
                {"province_id": 31, "lat": -6.18, "lon": 106.83}),
    "fx": ("fx_usdidr_week.json", "usdidr_20261015_20261021.json",
           {"base": "USD", "quote": "IDR"}),
}


def write_bronze(bronze: Path, sources=tuple(FIXTURE)) -> None:
    for source in sources:
        sample, name, params = FIXTURE[source]
        day = bronze / source / "2026-10-25"
        day.mkdir(parents=True)
        shutil.copy(SAMPLES / sample, day / name)
        row = {
            "request_key": f"test|{source}", "kind": "test", "params": params,
            "status": "ok", "http_status": 200, "file_path": f"{source}/2026-10-25/{name}",
            "n_rows": 1, "error": None, "fetched_at": "2026-10-25T07:30:00+00:00",
        }
        (bronze / source / "_manifest.jsonl").write_text(json.dumps(row) + "\n")


def dbt_build(tmp: Path) -> tuple[subprocess.CompletedProcess, Path]:
    db_path = tmp / "test.duckdb"
    env = {
        **os.environ, "PANGANWATCH_DB": str(db_path),
        "PANGANWATCH_BRONZE": (tmp / "bronze").as_posix(),
        "PYTHONUTF8": "1", "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
    }
    result = subprocess.run(
        [str(DBT), "build", "--profiles-dir", ".", "--target-path", str(tmp / "target")],
        cwd=ROOT / "dbt", env=env, capture_output=True, text=True, encoding="utf-8",
    )
    return result, db_path


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> duckdb.DuckDBPyConnection:
    if not DBT.exists():
        pytest.skip("dbt not installed in this environment")
    tmp = tmp_path_factory.mktemp("dbt")
    write_bronze(tmp / "bronze")
    result, db_path = dbt_build(tmp)
    assert result.returncode == 0, result.stdout[-4000:]
    con = duckdb.connect(str(db_path), read_only=True)
    yield con
    con.close()


def test_builds_when_only_pihps_was_fetched(tmp_path):
    # A fresh checkout with no BPS key: missing sources must give empty tables, not errors.
    if not DBT.exists():
        pytest.skip("dbt not installed in this environment")
    write_bronze(tmp_path / "bronze", sources=("pihps",))
    result, db_path = dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout[-4000:]
    con = duckdb.connect(str(db_path), read_only=True)
    assert con.execute("select count(*) from stg_cpi").fetchone() == (0,)
    assert con.execute("select count(*) from fct_daily_price").fetchone()[0] > 0
    con.close()


def one(db, sql, params=None):
    return db.execute(sql, params or []).fetchone()


# --- PIHPS ------------------------------------------------------------------------------

def test_silver_unpivots_level2_rows_only(db):
    n, commodities = one(db, """select count(*), list(distinct commodity_id order by commodity_id)
                                from stg_pihps_price""")
    # 2 commodities (rawit hijau, rawit merah) x 9 published days; category row dropped
    assert n == 18
    assert commodities == ["cabai_rawit_hijau", "cabai_rawit_merah"]


def test_silver_price_matches_website(db):
    price = one(db, """select price_idr_per_unit from stg_pihps_price
                       where commodity_id = 'cabai_rawit_merah' and date = '2026-10-13'""")[0]
    assert price == 89_400  # "89,400" on the PIHPS table for DKI Jakarta, 13/10/2026


def test_weekend_not_invented(db):
    n = one(db, "select count(*) from stg_pihps_price where date in ('2026-10-17', '2026-10-18')")
    assert n == (0,)


def test_gold_province_and_changes(db):
    row = one(db, """select province_id, n_cities, price_idr from fct_daily_price
                     where commodity_id = 'cabai_rawit_merah' and date = '2026-10-23'""")
    assert row == (31, 1, 81_650)
    chg = one(db, """select chg_1d_pct from fct_price_change
                     where commodity_id = 'cabai_rawit_merah' and date = '2026-10-23'""")[0]
    assert chg == pytest.approx(81_650 / 80_850 - 1)


# --- calendar ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("day", "to_lebaran", "since_lebaran", "is_ramadan"),
    [
        ("2025-03-31", 0, 0, False),     # Idul Fitri 1446 H
        ("2025-03-21", 10, 345, True),
        ("2026-03-19", 1, 353, True),
        ("2026-10-25", 136, 219, False),
    ],
)
def test_calendar_days_to_lebaran(db, day, to_lebaran, since_lebaran, is_ramadan):
    got = one(db, """select days_to_lebaran, days_since_lebaran, is_ramadan
                     from dim_date where date = ?""", [day])
    assert got == (to_lebaran, since_lebaran, is_ramadan)


# --- BPS CPI ----------------------------------------------------------------------------

def test_cpi_keys_decoded(db):
    # national food CPI (group 1552), 2022=100: Jan 111.86, Mar 112.84 (2025)
    rows = db.execute("""select month, index_value from stg_cpi
                         where region_level = 'national' and group_code = 1552
                           and month in ('2025-01-01', '2025-03-01') order by month""").fetchall()
    assert [r[1] for r in rows] == [pytest.approx(111.86), pytest.approx(112.84)]


def test_cpi_city_mapped_to_pihps(db):
    # BPS "KOTA MEDAN" -> PIHPS Kota Medan (city 4), Sumatera Utara (12)
    row = one(db, """select city_id, province_id, index_value from stg_cpi
                     where region_name = 'KOTA MEDAN' and group_code = 1552
                       and month = '2025-03-01'""")
    assert row == (4, 12, pytest.approx(112.09))


def test_cpi_12_months_per_region_group(db):
    n = one(db, "select count(*) from stg_cpi")[0]
    assert n == 3 * 2 * 12  # regions x groups x months


# --- weather and FX ---------------------------------------------------------------------

def test_weather_zipped_correctly(db):
    row = one(db, """select rain_mm, temp_max_c from stg_weather
                     where province_id = 31 and date = '2026-10-24'""")
    assert row == (pytest.approx(5.4), pytest.approx(32.7))


def test_fx_weekend_forward_filled_and_flagged(db):
    rows = db.execute("""select date::varchar, usd_idr, is_filled from stg_fx
                         where date between '2026-10-16' and '2026-10-19'
                         order by date""").fetchall()
    assert rows == [
        ("2026-10-16", 18031, False),
        ("2026-10-17", 18031, True),   # Saturday: Friday's rate carried forward
        ("2026-10-18", 18031, True),
        ("2026-10-19", 18043, False),
    ]
