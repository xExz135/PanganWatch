"""Rolling-origin backtest (spec: one cutoff every 4 weeks over the last 12 months).

For each fold:
  * train  = every row dated before the cutoff; the last `validation_days` of it are also
             handed over separately for early stopping / tuning (never the test window);
  * test   = run dates from the cutoff up to the next cutoff. On each run date the fitted
             model forecasts every horizon using only rows dated before that run date,
             exactly like the daily job (weekly retrain, daily forecasts).
target_date = run_date + horizon_days. A forecast is scored only if PIHPS published a
non-imputed price on its target date; forecasts with no actual stay unscored.

The harness slices the data itself, so a model can't see rows dated on or after the run
date even by mistake. Forecasters implement:
    fit(train, valid, horizons) -> fitted
    fitted.predict(history, run_date, horizons) -> keys, horizon_days, target_date, q10..q90

Run on a database (prints a summary; writes nothing to the shared DB before Gate 1):
    python -m ml.backtest [--db PATH] [--models naive,seasonal_naive,lgbm_quantile] [--out CSV]
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml import metrics
from ml.settings import settings


@dataclass(frozen=True)
class Fold:
    fold_id: int
    valid_start: pd.Timestamp  # first day of the validation slice (inside training data)
    cutoff: pd.Timestamp       # first day not in training = first run date
    test_end: pd.Timestamp     # first day after the last run date of this fold


def make_folds(last_date, n_cutoffs: int | None = None, step_days: int | None = None,
               validation_days: int | None = None) -> list[Fold]:
    """Cutoffs every `step_days`, the last test window ending on `last_date` (inclusive)."""
    cfg = settings()["backtest"]
    n = n_cutoffs or cfg["n_cutoffs"]
    step = pd.Timedelta(days=step_days or cfg["cutoff_step_days"])
    val = pd.Timedelta(days=validation_days or cfg["validation_days"])
    end = pd.Timestamp(last_date) + pd.Timedelta(days=1)
    folds = []
    for i, k in enumerate(range(n, 0, -1)):
        cutoff = end - k * step
        folds.append(Fold(i, cutoff - val, cutoff, cutoff + step))
    return folds


def run_backtest(history: pd.DataFrame, forecasters: Iterable, folds: list[Fold],
                 horizons: list[int] | None = None, origin_every_days: int | None = None,
                 season_days: int | None = None) -> pd.DataFrame:
    """Forecasts of every forecaster for every fold, with actuals and MASE scales attached."""
    cfg = settings()
    keys = list(cfg["target"]["series_keys"])
    horizons = horizons or list(cfg["backtest"]["horizons"])
    every = pd.Timedelta(days=origin_every_days or cfg["backtest"]["origin_every_days"])
    season = season_days or cfg["metrics"]["season_days"]

    hist = history.copy()
    hist["date"] = pd.to_datetime(hist["date"])
    if "is_imputed" not in hist:
        hist["is_imputed"] = False
    hist = hist.sort_values(["date", *keys], kind="stable").reset_index(drop=True)
    dates = hist["date"].to_numpy()

    def before(ts: pd.Timestamp) -> pd.DataFrame:
        return hist.iloc[: np.searchsorted(dates, np.datetime64(ts), side="left")]

    out, scales = [], []
    for fold in folds:
        train = before(fold.cutoff)
        if train.empty:
            continue
        valid = train[train["date"] >= fold.valid_start]
        scale = (train.groupby(keys)
                 .apply(lambda g: metrics.seasonal_naive_scale(g.set_index("date")["y"], season),
                        include_groups=False)
                 .rename("mase_scale").reset_index().assign(fold_id=fold.fold_id))
        scales.append(scale)
        for forecaster in forecasters:
            fitted = forecaster.fit(train, valid, horizons=horizons)
            run_date = fold.cutoff
            while run_date < fold.test_end:
                pred = fitted.predict(before(run_date), run_date.date(), horizons)
                if len(pred):
                    _check_prediction(pred, run_date, horizons, forecaster.name)
                    out.append(pred.assign(model_name=forecaster.name, fold_id=fold.fold_id,
                                           cutoff=fold.cutoff, run_date=run_date))
                run_date += every
    if not out:
        return pd.DataFrame()
    res = pd.concat(out, ignore_index=True)
    res["target_date"] = pd.to_datetime(res["target_date"])

    actual = (hist.loc[~hist["is_imputed"].astype(bool), [*keys, "date", "y"]]
              .rename(columns={"date": "target_date", "y": "actual"}))
    res = res.merge(actual, on=[*keys, "target_date"], how="left")
    return res.merge(pd.concat(scales, ignore_index=True), on=[*keys, "fold_id"], how="left")


def _check_prediction(pred: pd.DataFrame, run_date: pd.Timestamp, horizons, name: str) -> None:
    bad_h = set(pred["horizon_days"]) - set(horizons)
    if bad_h:
        raise ValueError(f"{name} returned horizons it was not asked for: {sorted(bad_h)}")
    expected = run_date + pd.to_timedelta(pred["horizon_days"], unit="D")
    if not (pd.to_datetime(pred["target_date"]) == expected).all():
        raise ValueError(f"{name}: target_date must equal run_date + horizon_days")


def label_segments(df: pd.DataFrame, calendar: pd.DataFrame,
                   post_lebaran_days: int | None = None) -> pd.DataFrame:
    """segment = ramadan_lebaran when the target date is in Ramadan or just after Lebaran."""
    post = post_lebaran_days if post_lebaran_days is not None else (
        settings()["segments"]["post_lebaran_days"])
    cal = calendar[["date", "is_ramadan", "days_since_lebaran"]].rename(
        columns={"date": "target_date"})
    cal["target_date"] = pd.to_datetime(cal["target_date"])
    merged = df.merge(cal, on="target_date", how="left")
    missing = merged["is_ramadan"].isna() & merged["actual"].notna()
    if missing.any():
        raise ValueError(f"calendar has no row for {merged.loc[missing, 'target_date'].min()}")
    in_ramadan = merged["is_ramadan"].fillna(False).astype(bool)
    holiday = in_ramadan | merged["days_since_lebaran"].between(0, post)
    merged["segment"] = np.where(holiday, "ramadan_lebaran", "normal")
    return merged.drop(columns=["is_ramadan", "days_since_lebaran"])


def evaluate(scored: pd.DataFrame, model_version: str, quantiles: list[float] | None = None,
             evaluated_at: datetime | None = None) -> pd.DataFrame:
    """Metrics shaped like fct_model_metrics, for segment all/normal/ramadan_lebaran and for
    each commodity plus all commodities (commodity_id NULL). Unscored rows are ignored."""
    qs = quantiles or list(settings()["backtest"]["quantiles"])
    qcol = {q: f"q{round(q * 100)}" for q in qs}
    df = scored[scored["actual"].notna()]
    if df.empty:
        return pd.DataFrame()
    df = pd.concat([df, df.assign(segment="all")], ignore_index=True)
    df = pd.concat([df, df.assign(commodity_id=None)], ignore_index=True)

    rows = []
    for (model, h, seg, com), g in df.groupby(
            ["model_name", "horizon_days", "segment", "commodity_id"], dropna=False):
        y, p50 = g["actual"], g[qcol[0.5]]
        values = {
            "mae": metrics.mae(y, p50),
            "smape": metrics.smape(y, p50),
            "mase": metrics.mase(y, p50, g["mase_scale"]),
            "pinball": float(np.mean([metrics.pinball(y, g[qcol[q]], q) for q in qs])),
        }
        if 0.1 in qcol and 0.9 in qcol:
            values["coverage_80"] = metrics.coverage(y, g[qcol[0.1]], g[qcol[0.9]])
        for metric, value in values.items():
            rows.append({
                "model_version": model_version, "model_name": model, "task": "forecast",
                "horizon_days": int(h), "segment": seg,
                "commodity_id": None if pd.isna(com) else com,
                "metric": metric, "value": value,
            })
    rows += _relative_rows(scored[scored["actual"].notna()], qcol[0.5], model_version)
    out = pd.DataFrame(rows)
    out["evaluated_at"] = evaluated_at or datetime.now(UTC)
    return out


def _relative_rows(df: pd.DataFrame, point_col: str, model_version: str) -> list[dict]:
    """Gate 3 metrics (owner-approved 2026-10-25), comparing each model with a baseline on
    exactly the same forecasts (same series, run date and target date):
      relmae_<ref>               geometric mean over series of MAE(model) / MAE(ref)
      relrmse_naive              same with RMSE (report only: shows whether big misses,
                                 mostly chili spikes, got worse; equivalent to Theil's U2)
      share_series_beating_naive share of series with MAE(model) < MAE(naive)
    Per-series ratios keep cheap and expensive commodities on an equal footing; the
    geometric mean is the fair average of ratios. A series whose reference error is 0 has no
    ratio; a ratio of 0 (model perfect) counts as a win but is left out of the mean."""
    refs = settings()["metrics"]["relative_to"]
    keys = list(settings()["target"]["series_keys"])
    if df.empty:
        return []
    df = df.assign(abs_error=(df["actual"] - df[point_col]).abs())
    df = pd.concat([df, df.assign(segment="all")], ignore_index=True)
    idx = [*keys, "segment", "horizon_days", "run_date", "target_date"]
    wide = df.pivot_table(index=idx, columns="model_name", values="abs_error")
    level = [*keys, "segment", "horizon_days"]
    rows = []
    for ref, names in refs.items():
        if ref not in wide:
            continue
        for model in wide.columns.drop(ref):
            pair = wide[[model, ref]].dropna()
            per_series = {
                "mae": pair.groupby(level=level).mean(),
                "rmse": np.sqrt((pair ** 2).groupby(level=level).mean()),
            }
            ratios = []
            for kind, metric in names.items():
                s = per_series[kind]
                s = s[s[ref] > 0]
                ratios.append((s[model] / s[ref]).rename(metric))
            ratio = pd.concat(ratios, axis=1).reset_index()
            for scope in (ratio, ratio.assign(commodity_id=None)):
                for (seg, h, com), g in scope.groupby(
                        ["segment", "horizon_days", "commodity_id"], dropna=False):
                    values = {}
                    for metric in names.values():
                        positive = g[metric][g[metric] > 0]
                        values[metric] = (float(np.exp(np.log(positive).mean()))
                                          if len(positive) else np.nan)
                    if ref == "naive":
                        mae_ratio = g[names["mae"]].dropna()
                        values["share_series_beating_naive"] = float((mae_ratio < 1).mean())
                    for name, value in values.items():
                        rows.append({
                            "model_version": model_version, "model_name": model,
                            "task": "forecast", "horizon_days": int(h), "segment": seg,
                            "commodity_id": None if pd.isna(com) else com,
                            "metric": name, "value": value,
                        })
    return rows


# --- command line ------------------------------------------------------------------------

def _forecasters(names: list[str], con=None) -> list:
    from ml.baselines import NaiveForecaster, SeasonalNaiveForecaster

    known = {"naive", "seasonal_naive", "lgbm_quantile"}
    unknown = set(names) - known
    if unknown:
        raise SystemExit(f"unknown models: {sorted(unknown)} (known: {sorted(known)})")
    out = []
    for n in names:
        if n == "naive":
            out.append(NaiveForecaster())
        elif n == "seasonal_naive":
            out.append(SeasonalNaiveForecaster())
        else:
            from ml.data import load_calendar, load_features
            from ml.lgbm import LGBMForecaster
            out.append(LGBMForecaster(features=load_features(con), calendar=load_calendar(con)))
    return out


def main(argv: list[str] | None = None) -> int:
    import duckdb

    from ml.data import load_calendar, load_history

    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=os.environ.get("PANGANWATCH_DB",
                                                  str(root / "data" / "panganwatch.duckdb")))
    ap.add_argument("--models", default="naive,seasonal_naive")
    ap.add_argument("--out", help="optional CSV of every scored forecast")
    args = ap.parse_args(argv)

    con = duckdb.connect(args.db, read_only=True)
    try:
        history, calendar = load_history(con), load_calendar(con)
        forecasters = _forecasters(args.models.split(","), con)
    finally:
        con.close()
    if history.empty:
        print("no price history in", args.db, file=sys.stderr)
        return 1
    folds = make_folds(history["date"].max())
    print(f"{len(folds)} folds, first cutoff {folds[0].cutoff:%Y-%m-%d}, "
          f"last run date {folds[-1].test_end - pd.Timedelta(days=1):%Y-%m-%d}")
    scored = label_segments(run_backtest(history, forecasters, folds), calendar)
    if args.out:
        scored.to_csv(args.out, index=False)
    m = evaluate(scored, model_version="baselines")
    summary = (m[(m["segment"] == "all") & m["commodity_id"].isna()]
               .pivot_table(index=["horizon_days", "model_name"], columns="metric",
                            values="value"))
    n = (scored[scored["actual"].notna()].groupby(["horizon_days", "model_name"]).size()
         .rename("n_scored"))
    print(summary.join(n).round(3).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
