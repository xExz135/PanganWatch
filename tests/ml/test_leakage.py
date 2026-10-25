"""Leakage harness: any use of a row dated >= run_date must make the check fail."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import pytest

from ml.backtest import make_folds, run_backtest
from ml.baselines import NaiveForecaster, SeasonalNaiveForecaster
from ml.leakage import LeakageError, check_no_lookahead

KEYS = ["commodity_id", "province_id"]
RUN_DATES = [date(2024, 6, 3), date(2024, 9, 13), date(2025, 1, 2)]


def _latest(frame: pd.DataFrame, run_date) -> pd.DataFrame:
    """The last row per series before run_date: what a feature row for run_date looks like."""
    past = frame[frame["date"] < pd.Timestamp(run_date)]
    return past.sort_values("date").groupby(KEYS).tail(1)


# --- feature functions: one honest, several leaky -----------------------------------------

def honest_rolling_mean(df, run_date):
    d = df.sort_values("date").copy()
    d["mean7"] = d.groupby(KEYS)["y"].transform(lambda s: s.rolling(7, min_periods=1).mean())
    return _latest(d, run_date)[[*KEYS, "date", "mean7"]]


def leaky_centered_window(df, run_date):
    d = df.sort_values("date").copy()
    d["mean7"] = d.groupby(KEYS)["y"].transform(
        lambda s: s.rolling(7, center=True, min_periods=1).mean())
    return _latest(d, run_date)[[*KEYS, "date", "mean7"]]


def leaky_next_value(df, run_date):
    d = df.sort_values("date").copy()
    d["next"] = d.groupby(KEYS)["y"].shift(-1)
    return _latest(d, run_date)[[*KEYS, "date", "next"]]


def leaky_full_sample_mean(df, run_date):
    d = df.copy()
    d["z"] = d["y"] / d.groupby(KEYS)["y"].transform("mean")
    return _latest(d, run_date)[[*KEYS, "date", "z"]]


def leaky_row_count(df, run_date):
    out = _latest(df, run_date)[[*KEYS, "date"]].copy()
    out["n_rows"] = len(df)
    return out


def test_honest_feature_passes(panel):
    check_no_lookahead(honest_rolling_mean, panel, RUN_DATES)


@pytest.mark.parametrize("fn", [leaky_centered_window, leaky_next_value,
                                leaky_full_sample_mean, leaky_row_count])
def test_leaky_features_are_caught(panel, fn):
    with pytest.raises(LeakageError):
        check_no_lookahead(fn, panel, RUN_DATES)


def test_check_refuses_to_pass_vacuously(panel):
    with pytest.raises(ValueError):
        check_no_lookahead(honest_rolling_mean, panel, [date(2030, 1, 1)])


@pytest.mark.parametrize("cls", [NaiveForecaster, SeasonalNaiveForecaster])
def test_baseline_predict_uses_no_future_rows(panel, cls):
    fitted = cls().fit(panel[panel["date"] < "2024-05-01"], None, horizons=[1, 7, 14, 28])
    check_no_lookahead(lambda df, rd: fitted.predict(df, rd, [1, 7, 14, 28]), panel, RUN_DATES)


# --- the backtest harness never hands a model a row dated on/after the run date ------------

@dataclass
class Spy:
    name: str = "spy"
    seen: list = field(default_factory=list)

    def fit(self, train, valid, horizons):
        self.seen.append(("fit", train["date"].max(), valid["date"].min(), None))
        return self

    def predict(self, history, run_date, horizons):
        self.seen.append(("predict", history["date"].max(), None, pd.Timestamp(run_date)))
        return pd.DataFrame(columns=[*KEYS, "horizon_days", "target_date", "q50"])


def test_harness_slices_before_cutoff_and_run_date(panel):
    spy = Spy()
    folds = make_folds(panel["date"].max(), n_cutoffs=3, step_days=28, validation_days=56)
    run_backtest(panel, [spy], folds, horizons=[1])
    fits = [s for s in spy.seen if s[0] == "fit"]
    assert len(fits) == 3
    for (_, train_max, valid_min, _), fold in zip(fits, folds, strict=True):
        assert train_max < fold.cutoff
        assert valid_min >= fold.valid_start
    predicts = [s for s in spy.seen if s[0] == "predict"]
    assert len(predicts) == 3 * 28  # one forecast per calendar day per fold
    assert all(seen_max < run_date for _, seen_max, _, run_date in predicts)
