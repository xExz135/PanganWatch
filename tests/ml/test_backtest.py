"""Backtest framework: folds, scoring rules, segments and the metrics table shape."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.backtest import evaluate, label_segments, make_folds, run_backtest
from ml.baselines import NaiveForecaster, SeasonalNaiveForecaster

CONTRACT_COLUMNS = ["model_version", "model_name", "task", "horizon_days", "segment",
                    "commodity_id", "metric", "value", "evaluated_at"]


def test_folds_every_four_weeks_over_the_last_year():
    folds = make_folds("2026-10-16")
    assert len(folds) == 13
    assert folds[-1].test_end == pd.Timestamp("2026-10-17")      # last run date = last data day
    assert folds[0].cutoff == pd.Timestamp("2026-10-17") - pd.Timedelta(days=364)
    for a, b in zip(folds, folds[1:], strict=False):
        assert b.cutoff - a.cutoff == pd.Timedelta(days=28)
        assert a.test_end == b.cutoff                              # windows tile, no overlap
    assert all(f.cutoff - f.valid_start == pd.Timedelta(days=56) for f in folds)


def _calendar(start="2023-01-01", end="2026-12-31", ramadan=("2025-03-01", "2025-03-30"),
              lebaran="2025-03-31") -> pd.DataFrame:
    dates = pd.date_range(start, end, freq="D")
    leb = pd.Timestamp(lebaran)
    since = (dates - leb).days
    return pd.DataFrame({
        "date": dates,
        "is_ramadan": (dates >= ramadan[0]) & (dates <= ramadan[1]),
        "days_since_lebaran": np.where(since >= 0, since, 999),
    })


def test_naive_on_constant_series_is_exact_and_covered():
    dates = pd.date_range("2024-01-01", periods=300, freq="D")
    flat = pd.DataFrame({"date": dates, "commodity_id": "x", "province_id": 31, "y": 100.0})
    folds = make_folds(dates.max(), n_cutoffs=2)
    res = run_backtest(flat, [NaiveForecaster()], folds, horizons=[1, 7])
    scored = res[res["actual"].notna()]
    assert (scored["q50"] == scored["actual"]).all()
    assert ((scored["q10"] <= scored["actual"]) & (scored["actual"] <= scored["q90"])).all()


def test_seasonal_naive_exact_on_weekly_pattern():
    dates = pd.date_range("2024-01-01", periods=300, freq="D")
    weekly = pd.DataFrame({"date": dates, "commodity_id": "x", "province_id": 31,
                           "y": 100.0 + 10 * dates.day_of_week})
    folds = make_folds(dates.max(), n_cutoffs=2)
    res = run_backtest(weekly, [SeasonalNaiveForecaster(season_days=7)], folds,
                       horizons=[1, 7, 14, 28])
    scored = res[res["actual"].notna()]
    assert len(scored) > 0
    assert np.allclose(scored["q50"], scored["actual"])


def test_scoring_rules(panel):
    panel = panel.copy()
    # one imputed price must never be used as an actual
    imputed_day = pd.Timestamp("2025-04-01")
    panel.loc[panel["date"] == imputed_day, "is_imputed"] = True
    folds = make_folds(panel["date"].max(), n_cutoffs=6)
    res = run_backtest(panel, [NaiveForecaster()], folds, horizons=[1, 7])

    assert (res["target_date"] == res["run_date"] + pd.to_timedelta(res["horizon_days"], "D")).all()
    assert res.loc[res["target_date"].dt.day_of_week >= 5, "actual"].isna().all()  # no weekend data
    assert res.loc[res["target_date"] == imputed_day, "actual"].isna().all()
    assert (res["q10"] <= res["q50"]).all() and (res["q50"] <= res["q90"]).all()
    assert res["mase_scale"].notna().all()


def test_segments_follow_target_date(panel):
    folds = make_folds(panel["date"].max(), n_cutoffs=13)
    res = label_segments(run_backtest(panel, [NaiveForecaster()], folds, horizons=[7]),
                         _calendar())
    holiday = res[res["segment"] == "ramadan_lebaran"]["target_date"]
    assert len(holiday) > 0
    assert holiday.min() >= pd.Timestamp("2025-03-01")
    assert holiday.max() <= pd.Timestamp("2025-04-07")   # Lebaran + 7 days
    assert (res.loc[res["target_date"] == pd.Timestamp("2025-04-08"), "segment"]
            == "normal").all()


def test_label_segments_refuses_missing_calendar(panel):
    folds = make_folds(panel["date"].max(), n_cutoffs=2)
    res = run_backtest(panel, [NaiveForecaster()], folds, horizons=[1])
    with pytest.raises(ValueError, match="calendar"):
        label_segments(res, _calendar(start="2025-12-01"))


def test_evaluate_matches_contract(panel):
    folds = make_folds(panel["date"].max(), n_cutoffs=13)
    res = run_backtest(panel, [NaiveForecaster(), SeasonalNaiveForecaster()], folds,
                       horizons=[1, 7, 14, 28])
    m = evaluate(label_segments(res, _calendar()), model_version="test")
    assert list(m.columns) == CONTRACT_COLUMNS
    assert set(m["segment"]) == {"all", "normal", "ramadan_lebaran"}
    assert set(m["metric"]) == {"mae", "smape", "mase", "pinball", "coverage_80",
                                "relmae_naive", "relrmse_naive", "relmae_snaive",
                                "share_series_beating_naive"}
    assert m["commodity_id"].isna().any() and m["commodity_id"].notna().any()
    assert not m.duplicated(["model_name", "horizon_days", "segment", "commodity_id",
                             "metric"]).any()
    # a random walk: naive should beat a weekly seasonal copy at short horizons
    allc = m[(m["segment"] == "all") & m["commodity_id"].isna() & (m["metric"] == "mae")
             & (m["horizon_days"] == 1)].set_index("model_name")["value"]
    assert allc["naive"] < allc["seasonal_naive"]


def test_relative_metrics_by_hand():
    """Series A: model error 5 vs naive 10 (ratio 0.5). Series B: 8 vs 4 (ratio 2).
    Geometric mean = sqrt(0.5 * 2) = 1; the model beats naive on 1 of 2 series.
    A forecast only the model made is not compared (same forecasts only)."""
    base = {"horizon_days": 7, "segment": "normal", "actual": 100.0, "mase_scale": 1.0,
            "province_id": 31, "target_date": pd.Timestamp("2025-01-10")}
    rows = []
    for com, run, naive_err, model_err in [("a", "2025-01-01", 10, 5), ("a", "2025-01-02", 10, 5),
                                           ("b", "2025-01-01", 4, 8)]:
        for name, err in [("naive", naive_err), ("model", model_err)]:
            rows.append({**base, "commodity_id": com, "run_date": pd.Timestamp(run),
                         "model_name": name, "q10": 100 - err, "q50": 100 - err, "q90": 100})
    rows.append({**base, "commodity_id": "b", "run_date": pd.Timestamp("2025-01-03"),
                 "model_name": "model", "q10": 0.0, "q50": 0.0, "q90": 100})
    m = evaluate(pd.DataFrame(rows), model_version="t")
    pick = m[(m["model_name"] == "model") & (m["segment"] == "all") & m["commodity_id"].isna()]
    got = pick.set_index("metric")["value"]
    assert got["relmae_naive"] == pytest.approx(1.0)
    assert got["relrmse_naive"] == pytest.approx(1.0)  # constant errors: same as MAE
    assert got["share_series_beating_naive"] == pytest.approx(0.5)
    per_a = m[(m["model_name"] == "model") & (m["commodity_id"] == "a")
              & (m["metric"] == "relmae_naive") & (m["segment"] == "all")]["value"]
    assert per_a.iloc[0] == pytest.approx(0.5)
    assert "relmae_snaive" not in set(m["metric"])  # no seasonal-naive run, no ratio


def test_relrmse_penalises_one_big_miss():
    """Same MAE as naive (errors 1 and 9 vs 5 and 5), but RMSE sqrt(41) vs 5: one big miss
    is worse than two medium ones, so relrmse_naive = sqrt(41) / 5 while relmae_naive = 1."""
    base = {"horizon_days": 7, "segment": "normal", "actual": 100.0, "mase_scale": 1.0,
            "province_id": 31, "commodity_id": "a", "target_date": pd.Timestamp("2025-01-10")}
    rows = []
    for run, naive_err, model_err in [("2025-01-01", 5, 1), ("2025-01-02", 5, 9)]:
        for name, err in [("naive", naive_err), ("model", model_err)]:
            rows.append({**base, "run_date": pd.Timestamp(run), "model_name": name,
                         "q10": 100 - err, "q50": 100 - err, "q90": 100})
    m = evaluate(pd.DataFrame(rows), model_version="t")
    got = m[(m["model_name"] == "model") & (m["segment"] == "all")
            & m["commodity_id"].isna()].set_index("metric")["value"]
    assert got["relmae_naive"] == pytest.approx(1.0)
    assert got["relrmse_naive"] == pytest.approx(41 ** 0.5 / 5)
    assert got["share_series_beating_naive"] == 0  # a tie is not a win
