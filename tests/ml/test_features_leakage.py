"""Leakage guard for fct_features: features dated on or before a cut-off must not change when
every input after the cut-off is removed (including CPI months not yet released by then).

Builds fct_features twice with dbt on copies of the shared sample database.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample" / "panganwatch_sample.duckdb"
DBT = Path(sys.executable).with_name("dbt.exe" if os.name == "nt" else "dbt")
CUTOFF = "2025-03-20"  # inside Ramadan 2025, with a year of history behind it
KEYS = ["date", "commodity_id", "province_id"]

pytestmark = pytest.mark.skipif(not (SAMPLE.exists() and DBT.exists()),
                                reason="needs the sample DB and dbt")


def dbt(db: Path, *args: str) -> None:
    env = {**os.environ, "PANGANWATCH_DB": str(db), "PYTHONUTF8": "1",
           "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    out = subprocess.run([str(DBT), *args, "--profiles-dir", ".",
                          "--target-path", str(db.parent / f"target_{db.stem}")],
                         cwd=ROOT / "dbt", env=env, capture_output=True, text=True,
                         encoding="utf-8")
    assert out.returncode == 0, out.stdout[-3000:]


def build_features(db: Path) -> pd.DataFrame:
    dbt(db, "seed", "--select", "production_centers", "fuel_price_events")
    dbt(db, "run", "--select", "fct_features")
    con = duckdb.connect(str(db), read_only=True)
    df = con.execute(f"select * from fct_features where date <= date '{CUTOFF}'").df()
    con.close()
    return df.sort_values(KEYS, ignore_index=True)


@pytest.fixture(scope="module")
def both(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("features")
    full, cut = tmp / "full.duckdb", tmp / "cut.duckdb"
    shutil.copy(SAMPLE, full)
    shutil.copy(SAMPLE, cut)
    con = duckdb.connect(str(cut))
    for table, column in [("fct_daily_price", "date"), ("stg_weather", "date"),
                          ("stg_fx", "date")]:
        con.execute(f"delete from {table} where {column} > date '{CUTOFF}'")
    con.execute(f"""delete from stg_cpi
                    where month + interval 1 month + interval 4 day > date '{CUTOFF}'""")
    con.close()
    return build_features(full), build_features(cut)


def test_cutoff_is_inside_the_sample(both):
    full, _ = both
    assert len(full) > 1000
    assert full["date"].max() <= pd.Timestamp(CUTOFF)


def test_features_do_not_see_the_future(both):
    full, cut = both
    assert len(full) == len(cut)
    # DuckDB may sum a window in a different order: allow float noise, nothing more
    pd.testing.assert_frame_equal(full, cut, check_exact=False, rtol=1e-9, atol=1e-9)
