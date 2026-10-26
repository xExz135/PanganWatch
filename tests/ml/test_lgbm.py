"""LightGBM forecaster: shape rules, no look-ahead, honest ranges, and it learns a signal."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")
from ml.backtest import make_folds, run_backtest  # noqa: E402
from ml.baselines import NaiveForecaster  # noqa: E402
from ml.leakage import check_no_lookahead  # noqa: E402
from ml.lgbm import LGBMForecaster, expand_origins  # noqa: E402
from ml.settings import settings  # noqa: E402

H = [1, 7]
FAST = {**settings()["lgbm"], "min_data_in_leaf": 20, "max_rounds": 60,
        "early_stopping_rounds": 10, "num_leaves": 15}


def toy_features(panel: pd.DataFrame, hint_horizon: int | None = None) -> pd.DataFrame:
    """A minimal fct_features: log price, a 7-day return, and optionally a 'hint' column
    carrying the future change (only to check that the model can learn something)."""
    f = panel[["date", "commodity_id", "province_id"]].copy()
    f["log_price"] = np.log(panel["y"])
    f = f.sort_values(["commodity_id", "province_id", "date"])
    g = f.groupby(["commodity_id", "province_id"])["log_price"]
    f["ret_7"] = f["log_price"] - g.shift(5)
    if hint_horizon:
        # the change to the price `hint_horizon` published days later
        f["hint"] = g.shift(-hint_horizon) - f["log_price"]
    return f.sort_values("date", ignore_index=True)


def toy_calendar(panel: pd.DataFrame) -> pd.DataFrame:
    d = pd.date_range(panel["date"].min() - pd.Timedelta(days=5),
                      panel["date"].max() + pd.Timedelta(days=60), freq="D")
    return pd.DataFrame({"date": d, "is_ramadan": False, "days_to_lebaran": 100,
                         "days_since_lebaran": 100, "is_holiday": False,
                         "day_of_week": d.day_of_week})


def model(panel, hint_horizon=None) -> LGBMForecaster:
    return LGBMForecaster(features=toy_features(panel, hint_horizon),
                          calendar=toy_calendar(panel), params=FAST)


def test_expand_origins_covers_weekends(panel):
    o = expand_origins(toy_features(panel), max_origins=3)
    fri = o[o["date"].dt.day_of_week == 4]
    # a Friday row serves Saturday, Sunday and Monday
    assert set((fri["run_date"] - fri["date"]).dt.days) == {1, 2, 3}
    assert (o["run_date"] > o["date"]).all()


def test_predictions_follow_the_contract(panel):
    train = panel[panel["date"] < "2025-03-01"]
    fitted = model(panel).fit(train, train[train["date"] >= "2025-01-01"], horizons=H)
    pred = fitted.predict(None, date(2025, 3, 3), H)
    assert len(pred) == 4 * len(H)
    assert (pred["target_date"] == pd.Timestamp("2025-03-03")
            + pd.to_timedelta(pred["horizon_days"], unit="D")).all()
    assert ((pred["q10"] <= pred["q50"]) & (pred["q50"] <= pred["q90"])).all()
    assert (pred[["q10", "q50", "q90"]] > 0).all().all()


def test_predict_uses_no_feature_rows_on_or_after_run_date(panel):
    train = panel[panel["date"] < "2025-03-01"]
    fitted = model(panel).fit(train, train[train["date"] >= "2025-01-01"], horizons=H)
    check_no_lookahead(
        lambda df, rd: replace(fitted, features=df, _origins=None).predict(None, rd, H),
        toy_features(panel), [date(2025, 3, 3), date(2025, 3, 8)],
        value_cols=["log_price", "ret_7"])


def test_fit_never_trains_on_targets_after_the_cutoff(panel):
    m = model(panel)
    cutoff = pd.Timestamp("2025-03-01")
    actual = panel[panel["date"] < cutoff]
    ex = m.examples(7, actual, cutoff)
    assert ex["target_date"].max() < cutoff
    assert (ex["date"] < ex["run_date"]).all()


def test_learns_a_real_signal_and_keeps_ranges_honest(panel):
    # with a hint of the future change in the features, the model must beat naive
    folds = make_folds(panel["date"].max(), n_cutoffs=2, step_days=28, validation_days=56)
    res = run_backtest(panel, [NaiveForecaster(), model(panel, hint_horizon=1)], folds,
                       horizons=[1])
    s = res[res["actual"].notna()]
    mae = s.assign(ae=(s["q50"] - s["actual"]).abs()).groupby("model_name")["ae"].mean()
    assert mae["lgbm_quantile"] < 0.8 * mae["naive"]
    lg = s[s["model_name"] == "lgbm_quantile"]
    coverage = ((lg["actual"] >= lg["q10"]) & (lg["actual"] <= lg["q90"])).mean()
    assert 0.6 <= coverage <= 0.97
