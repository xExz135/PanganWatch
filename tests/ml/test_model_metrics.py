"""fct_model_metrics: committed backtest summary -> table, idempotent per version."""

from __future__ import annotations

import duckdb
import pandas as pd

from ml.backtest import make_folds, run_backtest
from ml.baselines import NaiveForecaster, SeasonalNaiveForecaster
from ml.model_metrics import COLUMNS, add, publish, read


def scored(panel):
    folds = make_folds(panel["date"].max(), n_cutoffs=2, step_days=28)
    res = run_backtest(panel, [NaiveForecaster(), SeasonalNaiveForecaster()], folds,
                       horizons=[1, 7])
    return res.assign(segment="normal")


def test_add_merges_versions_and_publish_mirrors_the_file(tmp_path, panel):
    path = tmp_path / "metrics.csv"
    s = scored(panel)
    add(s, "backtest-1", path=path)
    add(s, "backtest-2", models=["seasonal_naive"], path=path)
    add(s, "backtest-2", models=["seasonal_naive"], path=path)  # re-add replaces, no dupes
    f = read(path)
    assert list(f.columns) == COLUMNS
    assert set(f["model_version"]) == {"backtest-1", "backtest-2"}
    assert set(f.loc[f["model_version"] == "backtest-2", "model_name"]) == {"seasonal_naive"}
    # the relative metric was computed against naive even though naive rows were dropped
    assert "relmae_naive" in set(f.loc[f["model_version"] == "backtest-2", "metric"])

    con = duckdb.connect(str(tmp_path / "m.duckdb"))
    assert publish(con, path) == len(f)
    assert publish(con, path) == len(f)  # idempotent
    n = con.execute("select count(*) from fct_model_metrics").fetchone()[0]
    assert n == len(f)
    total = con.execute("""select value from fct_model_metrics where model_version = 'backtest-1'
                           and model_name = 'naive' and horizon_days = 7 and segment = 'all'
                           and commodity_id is null and metric = 'mae'""").fetchone()[0]
    s7 = s[(s["model_name"] == "naive") & (s["horizon_days"] == 7) & s["actual"].notna()]
    assert abs(total - (s7["q50"] - s7["actual"]).abs().mean()) < 1e-6
    con.close()


def test_committed_file_matches_the_contract():
    f = read()
    if f.empty:
        return
    assert list(f.columns) == COLUMNS
    assert set(f["segment"]) <= {"all", "normal", "ramadan_lebaran"}
    assert not f.duplicated(["model_version", "model_name", "horizon_days", "segment",
                             "commodity_id", "metric"]).any()
    assert pd.notna(f["evaluated_at"]).all()
