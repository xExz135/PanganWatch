"""The live loop: ml.forecast publishes, ml.ledger scores, dbt/models/ml audits both."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from ml.forecast import make_forecast, publish
from ml.leakage import check_no_lookahead
from ml.ledger import score

ROOT = Path(__file__).resolve().parents[2]
HORIZONS = [1, 7, 14, 28]
RUN = date(2025, 3, 3)  # a Monday inside the toy panel (2024-01-01 + 500 days)


def make_db(path, panel: pd.DataFrame):
    con = duckdb.connect(str(path))
    prices = panel.assign(market_tier="traditional", price_idr=panel["y"].astype("int64"))
    con.register("p", prices)
    con.execute("""
        create table fct_daily_price as
        select date::date as date, commodity_id, province_id, market_tier, price_idr, is_imputed
        from p
    """)
    con.unregister("p")
    return con


@pytest.fixture
def con(tmp_path, panel):
    # history ends the day before RUN; actuals are added by each test as needed
    c = make_db(tmp_path / "live.duckdb", panel[panel["date"] < pd.Timestamp(RUN)])
    yield c
    c.close()


def add_actuals(con, panel: pd.DataFrame, upto: date, imputed: bool = False):
    new = panel[(panel["date"] >= pd.Timestamp(RUN)) & (panel["date"] <= pd.Timestamp(upto))]
    new = new.assign(market_tier="traditional", price_idr=new["y"].astype("int64"),
                     is_imputed=imputed)
    con.register("n", new)
    con.execute("""insert into fct_daily_price select date::date, commodity_id, province_id,
                   market_tier, price_idr, is_imputed from n""")
    con.unregister("n")


# --- forecasts --------------------------------------------------------------------------

def test_forecast_shape_and_naive_rule(panel):
    fc = make_forecast(panel, RUN, "naive", HORIZONS)
    assert len(fc) == 4 * len(HORIZONS)  # 2 commodities x 2 provinces x horizons
    assert (fc["target_date"] == fc["run_date"] + pd.to_timedelta(fc["horizon_days"], "D")).all()
    assert ((fc["q10"] <= fc["q50"]) & (fc["q50"] <= fc["q90"])).all()
    assert (fc["q10"] < fc["q90"]).all()  # a real range, not a point
    last = (panel[panel["date"] < pd.Timestamp(RUN)].sort_values("date")
            .groupby(["commodity_id", "province_id"])["y"].last())
    for _, r in fc.iterrows():
        assert r["q50"] == round(last[(r["commodity_id"], r["province_id"])])


def test_forecast_uses_no_future_rows(panel):
    check_no_lookahead(lambda df, rd: make_forecast(df, rd, "naive", HORIZONS), panel,
                       [date(2024, 9, 2), RUN])


def test_unknown_model_is_an_error(panel):
    with pytest.raises(ValueError):
        make_forecast(panel, RUN, "crystal_ball", HORIZONS)


def test_publish_is_append_only_and_idempotent(con):
    n = publish(con, RUN, "naive", today=RUN)
    assert n == 4 * len(HORIZONS)
    first = con.execute("select * from fct_forecast order by all").df()
    assert publish(con, RUN, "naive", today=RUN) == 0  # re-run: nothing written
    assert first.equals(con.execute("select * from fct_forecast order by all").df())
    assert first["model_version"].str.startswith("naive-").all()


def test_publish_refuses_past_dates(con):
    assert publish(con, RUN, "naive", today=RUN + timedelta(days=1)) == 0
    assert con.execute("select count(*) from fct_forecast").fetchone()[0] == 0


# --- ledger -----------------------------------------------------------------------------

def test_ledger_scores_only_published_non_imputed_targets(con, panel):
    publish(con, RUN, "naive", today=RUN)
    add_actuals(con, panel, RUN + timedelta(days=7))  # covers h=1 and h=7 targets

    # targets before the ledger date with a price: h=1 (Tue) and h=7 (Mon) -> 2 x 4 series
    assert score(con, RUN + timedelta(days=8)) == 8
    assert score(con, RUN + timedelta(days=8)) == 0  # never rescored
    led = con.execute("""
        select l.*, f.q10, f.q50, f.q90 from fct_forecast_ledger l join fct_forecast f
        using (run_date, model_version, commodity_id, province_id, horizon_days)""").df()
    assert set(led["horizon_days"]) == {1, 7}
    assert (led["abs_error"] == (led["q50"] - led["actual_price"]).abs()).all()
    assert (led["pct_error"] - led["abs_error"] / led["actual_price"]).abs().max() < 1e-12
    inside = (led["actual_price"] >= led["q10"]) & (led["actual_price"] <= led["q90"])
    assert (led["in_interval_80"] == inside).all()


def test_ledger_waits_for_the_target_day_to_pass(con, panel):
    publish(con, RUN, "naive", today=RUN)
    add_actuals(con, panel, RUN + timedelta(days=1))
    assert score(con, RUN + timedelta(days=1)) == 0  # target == ledger date: not yet
    assert score(con, RUN + timedelta(days=2)) == 4


def test_ledger_skips_weekend_and_imputed_targets(con, panel):
    publish(con, RUN, "naive", today=RUN)
    # h=14 targets fall on a Monday two weeks out; make those prices imputed
    add_actuals(con, panel, RUN + timedelta(days=14), imputed=True)
    assert score(con, RUN + timedelta(days=30)) == 0
    # h=28 targets: no price published yet (late data), so nothing to score
    assert con.execute("select count(*) from fct_forecast_ledger").fetchone()[0] == 0


# --- dbt audit models -------------------------------------------------------------------

DBT = Path(sys.executable).with_name("dbt.exe" if os.name == "nt" else "dbt")


def dbt_ml(db_path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PANGANWATCH_DB": str(db_path), "PYTHONUTF8": "1",
           "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    return subprocess.run(
        [str(DBT), "build", "--profiles-dir", ".",
         "--select", "ml_forecast_audit", "ml_ledger_audit",
         "--target-path", str(Path(db_path).parent / "target")],
        cwd=ROOT / "dbt", env=env, capture_output=True, text=True, encoding="utf-8")


@pytest.mark.skipif(not DBT.exists(), reason="dbt not installed in this environment")
def test_dbt_audits_pass_on_honest_tables_and_catch_a_backdated_forecast(tmp_path, panel):
    con = make_db(tmp_path / "audit.duckdb", panel[panel["date"] < pd.Timestamp(RUN)])
    publish(con, RUN, "naive", today=RUN)
    # created_at is real "now"; move it into RUN's day so the honest case is honest
    con.execute("update fct_forecast set created_at = timestamp '2025-03-03 07:00:00'")
    add_actuals(con, panel, RUN + timedelta(days=7))
    score(con, RUN + timedelta(days=8))
    con.close()

    ok = dbt_ml(tmp_path / "audit.duckdb")
    assert ok.returncode == 0, ok.stdout[-3000:]

    con = duckdb.connect(str(tmp_path / "audit.duckdb"))
    con.execute("""update fct_forecast set created_at = timestamp '2025-03-05 07:00:00'
                   where horizon_days = 28""")  # rewritten two days after its run date
    con.close()
    bad = dbt_ml(tmp_path / "audit.duckdb")
    assert bad.returncode != 0
    assert "written_after_run_date" in bad.stdout
