"""A2 transmission: the regression recovers a known, asymmetric pass-through."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("statsmodels")
from analytics import transmission  # noqa: E402
from analytics.run import main  # noqa: E402

RISE, FALL = 0.6, 0.2  # same-month pass-through of producer rises / falls, nothing later


def synthetic_chain(path, n_provinces=12, n_months=48, seed=0):
    """Daily fct_margin_chain rows: producer fixed within a month, retail = monthly level."""
    rng = np.random.default_rng(seed)
    rows = []
    months = pd.date_range("2022-01-01", periods=n_months, freq="MS")
    for pid in range(1, n_provinces + 1):
        lp = np.log(20000) + np.cumsum(rng.normal(0, 0.08, n_months))
        dp = np.diff(lp, prepend=lp[0])
        dr = RISE * np.clip(dp, 0, None) + FALL * np.clip(dp, None, 0) \
            + rng.normal(0, 0.005, n_months)
        lr = np.log(30000) + np.cumsum(dr)
        for m, p, r in zip(months, lp, lr, strict=True):
            for day in pd.date_range(m, m + pd.offsets.MonthEnd(0), freq="B"):
                rows.append((day.date(), "cabai_rawit_merah", pid, round(np.exp(p)),
                             round(np.exp(r))))
    df = pd.DataFrame(rows, columns=["date", "commodity_id", "province_id",
                                     "producer_price", "retail_price"])
    con = duckdb.connect(str(path))
    con.register("rows", df)
    con.execute("""create table fct_margin_chain as
                   select date::date as date, commodity_id, province_id::integer as province_id,
                          producer_price::bigint as producer_price,
                          retail_price::bigint as retail_price
                   from rows""")
    con.unregister("rows")
    return con


def test_recovers_known_asymmetric_pass_through(tmp_path):
    con = synthetic_chain(tmp_path / "chain.duckdb")
    lags, summary = transmission.run(con)
    s = summary.iloc[0]
    assert s["n_provinces"] == 12
    assert s["rise_same_month"] == pytest.approx(RISE, abs=0.05)
    assert s["fall_same_month"] == pytest.approx(FALL, abs=0.05)
    assert s["rise_total"] == pytest.approx(RISE, abs=0.08)  # later lags ~ 0
    assert s["p_value_equal_same_month"] < 0.001
    assert bool(s["is_asymmetric"])
    assert set(lags["lag_months"]) == set(range(transmission.LAGS + 1))


def test_symmetric_pass_through_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "FALL", RISE)
    con = synthetic_chain(tmp_path / "sym.duckdb", seed=1)
    _, summary = transmission.run(con)
    assert summary.iloc[0]["p_value_equal_totals"] > 0.05


def test_too_few_provinces_are_skipped(tmp_path):
    con = synthetic_chain(tmp_path / "few.duckdb", n_provinces=3)
    lags, summary = transmission.run(con)
    assert summary.empty and lags.empty


def test_incomplete_month_is_left_out(tmp_path):
    con = synthetic_chain(tmp_path / "cut.duckdb", n_months=30)
    _, summary = transmission.run(con, before="2024-06-15")
    assert str(summary.iloc[0]["last_month"]) == "2024-05-01"


def test_entry_point_writes_tables_and_is_repeatable(tmp_path):
    db = tmp_path / "run.duckdb"
    synthetic_chain(db).close()
    assert main(["--db", str(db), "--date", "2026-01-15"]) == 0
    assert main(["--db", str(db), "--date", "2026-01-15"]) == 0  # replace, not append
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("select count(*) from ana_a2_transmission_summary").fetchone()[0] == 1
    n_lags = con.execute("select count(*) from ana_a2_transmission_lags").fetchone()[0]
    assert n_lags == 2 * (transmission.LAGS + 1)
