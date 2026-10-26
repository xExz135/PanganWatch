"""lgbm_routed: LightGBM per commodity only where it beat the baseline on validation data."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

pytest.importorskip("lightgbm")
from ml.baselines import NaiveForecaster  # noqa: E402
from ml.leakage import check_no_lookahead  # noqa: E402
from ml.lgbm import LGBMForecaster  # noqa: E402
from ml.routed import RoutedForecaster, choose  # noqa: E402
from tests.ml.test_lgbm import FAST, toy_calendar, toy_features  # noqa: E402

H = [1, 7]
RUN = date(2025, 3, 3)
CHILI, RICE = "cabai_rawit_merah", "beras_medium_1"


def test_choose_needs_a_validation_win_beyond_the_margin():
    v = {7: pd.DataFrame({"commodity_id": [CHILI, RICE], "mae_model": [90.0, 101.0],
                          "mae_naive": [100.0, 100.0], "n": [500, 500]})}
    assert choose(v, 0.0) == {(CHILI, 7)}
    assert choose(v, 0.2) == set()  # a 10% win is not enough when 20% is required


def chili_only_hint(panel):
    # the model gets a hint of tomorrow's change for chili only: it should win there
    f = toy_features(panel, hint_horizon=1)
    f.loc[f["commodity_id"] == RICE, "hint"] = 0.0
    return f


@pytest.fixture
def fitted(panel):
    m = LGBMForecaster(features=chili_only_hint(panel), calendar=toy_calendar(panel), params=FAST)
    train = panel[panel["date"] < pd.Timestamp(RUN)]
    return RoutedForecaster(model=m, min_gain=0.0).fit(
        train, train[train["date"] >= pd.Timestamp("2025-01-06")], horizons=H)


def test_routes_the_commodity_where_the_model_won_on_validation(fitted):
    assert (CHILI, 1) in fitted.use_model
    v = fitted.model.validation[1].set_index("commodity_id")
    assert v.loc[CHILI, "mae_model"] < v.loc[CHILI, "mae_naive"]


def test_prediction_takes_each_row_from_the_chosen_model(fitted, panel):
    hist = panel[panel["date"] < pd.Timestamp(RUN)]
    out = fitted.predict(hist, RUN, H)
    base = NaiveForecaster().fit(hist, horizons=H).predict(hist, RUN, H)
    lgb = fitted.model.predict(hist, RUN, H)
    assert len(out) == len(base)  # every series once per horizon
    k = ["commodity_id", "province_id", "horizon_days"]
    for _, r in out.iterrows():
        src = lgb if (r["commodity_id"], r["horizon_days"]) in fitted.use_model else base
        row = src.set_index(k).loc[tuple(r[k])]
        assert r["q50"] == pytest.approx(row["q50"])


def test_routed_forecast_uses_no_future_rows(fitted, panel):
    check_no_lookahead(lambda df, rd: fitted.predict(df, rd, H), panel[["date", "commodity_id",
                       "province_id", "y", "is_imputed"]], [RUN])
