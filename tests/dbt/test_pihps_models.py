"""Run dbt on a tiny bronze fixture (one saved real response) and check silver/gold values."""

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
SAMPLE = ROOT / "tests" / "samples" / "pihps_grid_jakarta_cabai_rawit.json"
DBT = Path(sys.executable).with_name("dbt.exe" if os.name == "nt" else "dbt")


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> duckdb.DuckDBPyConnection:
    if not DBT.exists():
        pytest.skip("dbt not installed in this environment")
    tmp = tmp_path_factory.mktemp("dbt")
    bronze = tmp / "bronze"
    day = bronze / "pihps" / "2026-10-25"
    day.mkdir(parents=True)
    shutil.copy(SAMPLE, day / "traditional_c34_20261013_20261024.json")
    manifest = {
        "request_key": "daily|2026-10-25|traditional|34", "kind": "daily",
        "params": {"market_tier": "traditional", "city_id": 34},
        "status": "ok", "http_status": 200,
        "file_path": "pihps/2026-10-25/traditional_c34_20261013_20261024.json",
        "n_rows": 3, "error": None, "fetched_at": "2026-10-25T07:30:00+00:00",
    }
    (bronze / "pihps" / "_manifest.jsonl").write_text(json.dumps(manifest) + "\n")

    db_path = tmp / "test.duckdb"
    env = {
        **os.environ, "PANGANWATCH_DB": str(db_path), "PANGANWATCH_BRONZE": bronze.as_posix(),
        "PYTHONUTF8": "1", "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
    }
    # Seeds pihps_cities/pihps_commodity_names come from ingestion.refs and must exist.
    result = subprocess.run(
        [str(DBT), "build", "--profiles-dir", ".", "--target-path", str(tmp / "target"),
         "--exclude", "test_type:singular"],
        cwd=ROOT / "dbt", env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout[-4000:]
    con = duckdb.connect(str(db_path), read_only=True)
    yield con
    con.close()


def test_silver_unpivots_level2_rows_only(db):
    n, commodities = db.execute(
        "select count(*), list(distinct commodity_id order by commodity_id) from stg_pihps_price"
    ).fetchone()
    # 2 commodities (rawit hijau, rawit merah) x 9 published days; category row dropped
    assert n == 18
    assert commodities == ["cabai_rawit_hijau", "cabai_rawit_merah"]


def test_silver_price_matches_website(db):
    price = db.execute(
        """select price_idr_per_unit from stg_pihps_price
           where commodity_id = 'cabai_rawit_merah' and date = '2026-10-13'"""
    ).fetchone()[0]
    assert price == 89_400  # "89,400" on the PIHPS table for DKI Jakarta, 13/10/2026


def test_weekend_not_invented(db):
    n = db.execute(
        "select count(*) from stg_pihps_price where date in ('2026-10-17', '2026-10-18')"
    ).fetchone()[0]
    assert n == 0


def test_gold_province_and_changes(db):
    row = db.execute(
        """select province_id, n_cities, price_idr from fct_daily_price
           where commodity_id = 'cabai_rawit_merah' and date = '2026-10-23'"""
    ).fetchone()
    assert row == (31, 1, 81_650)
    chg = db.execute(
        """select chg_1d_pct from fct_price_change
           where commodity_id = 'cabai_rawit_merah' and date = '2026-10-23'"""
    ).fetchone()[0]
    assert chg == pytest.approx(81_650 / 80_850 - 1)


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
    got = db.execute(
        "select days_to_lebaran, days_since_lebaran, is_ramadan from dim_date where date = ?",
        [day],
    ).fetchone()
    assert got == (to_lebaran, since_lebaran, is_ramadan)
