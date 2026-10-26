"""Global LightGBM quantile forecaster (spec Week 8): one model per horizon and quantile.

Target: log(price on the target date) - log(price on the feature date), i.e. the log change
from the last published price. A forecast issued on run_date uses the latest fct_features
row dated before run_date (Friday's row serves Saturday, Sunday and Monday run dates);
`gap_days_to_run` tells the model how stale that row is. Calendar facts of the target date
are known in advance and are inputs too.

Training examples are built from fct_features (leak-free by construction, proven by
tests/ml/test_features_leakage.py) and the actual prices the backtest harness hands to
fit(), so a target after the fold's cutoff can't be used. Each fold's validation slice is
split in two: the first half stops boosting early, the second calibrates the 80% range
(conformalized quantile regression, in log space).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from ml.settings import settings

KEYS = ["commodity_id", "province_id"]
NOT_FEATURES = {"date", *KEYS}
CATEGORICAL = KEYS
CALENDAR_AT_TARGET = ["is_ramadan", "days_to_lebaran", "days_since_lebaran", "is_holiday",
                      "day_of_week"]


def _qcol(q: float) -> str:
    return f"q{round(q * 100)}"


def feature_columns(features: pd.DataFrame) -> list[str]:
    return [c for c in features.columns if c not in NOT_FEATURES]


def expand_origins(features: pd.DataFrame, max_origins: int) -> pd.DataFrame:
    """One row per (feature row, run date it serves). A row dated d serves run dates
    d+1 .. min(next row date, d + max_origins) for its series."""
    f = features.sort_values([*KEYS, "date"], kind="stable")
    nxt = f.groupby(KEYS, observed=True)["date"].shift(-1)
    gap = (nxt - f["date"]).dt.days.fillna(1).clip(lower=1, upper=max_origins).astype(int)
    rows = np.repeat(np.arange(len(f)), gap.to_numpy())
    out = f.iloc[rows].reset_index(drop=True)
    offset = np.concatenate([np.arange(1, g + 1) for g in gap.to_numpy()])
    out["run_date"] = out["date"] + pd.to_timedelta(offset, unit="D")
    out["gap_days_to_run"] = offset
    return out


def add_target_calendar(x: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    cal = calendar[["date", *CALENDAR_AT_TARGET]].rename(
        columns={"date": "target_date", **{c: f"target_{c}" for c in CALENDAR_AT_TARGET}})
    out = x.merge(cal, on="target_date", how="left")
    for c in ("target_is_ramadan", "target_is_holiday"):
        out[c] = out[c].astype("float")
    return out


@dataclass
class LGBMForecaster:
    features: pd.DataFrame
    calendar: pd.DataFrame
    name: str = "lgbm_quantile"
    quantiles: list[float] = field(
        default_factory=lambda: list(settings()["backtest"]["quantiles"]))
    max_staleness_days: int = field(
        default_factory=lambda: settings()["baselines"]["max_staleness_days"])
    params: dict = field(default_factory=lambda: dict(settings()["lgbm"]))
    models: dict = field(default_factory=dict)        # (horizon, quantile) -> Booster
    widen: dict = field(default_factory=dict)          # horizon -> log-space widening of 80%
    best_rounds: dict = field(default_factory=dict)    # (horizon, quantile) -> rounds
    # horizon -> per-commodity MAE of q50 and of the last price on the calibration half of the
    # validation slice (data before the fold's cutoff); ml.routed picks a model from it
    validation: dict = field(default_factory=dict)
    _origins: pd.DataFrame | None = field(default=None, repr=False)

    def __post_init__(self):
        f = self.features.copy()
        f["date"] = pd.to_datetime(f["date"])
        for c in CATEGORICAL:
            f[c] = f[c].astype("category")
        for c in f.columns:
            if c not in NOT_FEATURES and f[c].dtype == bool:
                f[c] = f[c].astype(float)
        self.features = f.sort_values("date", kind="stable").reset_index(drop=True)
        self._dates = self.features["date"].to_numpy()

    # --- examples ---------------------------------------------------------------------------
    def origins(self) -> pd.DataFrame:
        if self._origins is None:
            self._origins = expand_origins(self.features, int(self.params["max_origins_per_row"]))
        return self._origins

    def examples(self, horizon: int, actual: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
        """Origins whose target date (run_date + horizon) is before cutoff, with the target."""
        o = self.origins()
        o = o[o["run_date"] + pd.Timedelta(days=horizon) < cutoff].copy()
        o["target_date"] = o["run_date"] + pd.Timedelta(days=horizon)
        y = actual.rename(columns={"date": "target_date"})
        x = o.merge(y, on=[*KEYS, "target_date"], how="inner")
        x["target"] = np.log(x["y"]) - x["log_price"]
        return add_target_calendar(x.drop(columns="y"), self.calendar)

    def x_columns(self, frame: pd.DataFrame) -> list[str]:
        base = feature_columns(self.features)
        extra = ["gap_days_to_run", *[f"target_{c}" for c in CALENDAR_AT_TARGET]]
        return [c for c in [*CATEGORICAL, *base, *extra] if c in frame.columns]

    # --- training -----------------------------------------------------------------------------
    def fit(self, train: pd.DataFrame, valid: pd.DataFrame | None = None,
            horizons: list[int] | None = None) -> LGBMForecaster:
        import lightgbm as lgb

        horizons = horizons or list(settings()["backtest"]["horizons"])
        train = train.copy()
        train["date"] = pd.to_datetime(train["date"])
        cutoff = train["date"].max() + pd.Timedelta(days=1)
        valid_start = (pd.to_datetime(valid["date"]).min() if valid is not None and len(valid)
                       else cutoff)
        valid_mid = valid_start + (cutoff - valid_start) / 2
        actual = train.loc[~train.get("is_imputed", False).astype(bool),
                           [*KEYS, "date", "y"]].copy()
        for c in CATEGORICAL:
            actual[c] = actual[c].astype(self.features[c].dtype)

        p = self.params
        lgb_params = {
            "objective": "quantile", "learning_rate": p["learning_rate"],
            "num_leaves": p["num_leaves"], "min_data_in_leaf": p["min_data_in_leaf"],
            "feature_fraction": p["feature_fraction"], "bagging_fraction": p["bagging_fraction"],
            "bagging_freq": p["bagging_freq"], "lambda_l2": p["lambda_l2"],
            "seed": p["seed"], "verbose": -1, "num_threads": 0,
        }
        fitted = replace(self, models={}, widen={}, best_rounds={}, validation={})
        rng = np.random.default_rng(p["seed"])
        for h in horizons:
            ex = self.examples(h, actual, cutoff)
            tr = ex[ex["target_date"] < valid_start]
            es = ex[(ex["target_date"] >= valid_start) & (ex["target_date"] < valid_mid)]
            cal = ex[ex["target_date"] >= valid_mid]
            if p["train_sample"] < 1.0 and len(tr):
                tr = tr[rng.random(len(tr)) < p["train_sample"]]
            if tr.empty:
                continue
            cols = self.x_columns(ex)
            # one binned dataset per horizon, shared by the three quantile models
            dtrain = lgb.Dataset(tr[cols], tr["target"], categorical_feature=CATEGORICAL,
                                 free_raw_data=False, params={"verbose": -1})
            dvalid = (lgb.Dataset(es[cols], es["target"], reference=dtrain, free_raw_data=False)
                      if len(es) else None)
            for q in self.quantiles:
                params = {**lgb_params, "alpha": q}
                valid_sets = [dvalid] if dvalid is not None else []
                callbacks = ([lgb.early_stopping(p["early_stopping_rounds"], verbose=False)]
                             if dvalid is not None else [])
                booster = lgb.train(params, dtrain, num_boost_round=p["max_rounds"],
                                    valid_sets=valid_sets, callbacks=callbacks)
                fitted.models[(h, q)] = booster
                fitted.best_rounds[(h, q)] = booster.best_iteration or booster.current_iteration()
            fitted.widen[h] = fitted._conformal_widen(h, cal, cols) if p["conformal"] else 0.0
            if len(cal):
                fitted.validation[h] = fitted._validation_mae(h, cal, cols)
        return fitted

    def _validation_mae(self, h: int, cal: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
        """Per commodity: MAE (rupiah) of this model's q50 and of the last published price."""
        mid = min(self.quantiles, key=lambda q: abs(q - 0.5))
        q50 = self._raw_quantiles(h, cal, cols)[mid]
        lp, target = cal["log_price"].to_numpy(), cal["target"].to_numpy()
        actual = np.exp(lp + target)
        return (pd.DataFrame({"commodity_id": cal["commodity_id"].astype(str).to_numpy(),
                              "mae_model": np.abs(np.exp(lp + q50) - actual),
                              "mae_naive": np.abs(np.exp(lp) - actual)})
                .groupby("commodity_id").agg(mae_model=("mae_model", "mean"),
                                             mae_naive=("mae_naive", "mean"),
                                             n=("mae_model", "size"))
                .reset_index())

    def _raw_quantiles(self, h: int, x: pd.DataFrame, cols: list[str]) -> dict[float, np.ndarray]:
        preds = {q: self.models[(h, q)].predict(x[cols], num_iteration=self.best_rounds[(h, q)])
                 for q in self.quantiles}
        stacked = np.sort(np.vstack([preds[q] for q in self.quantiles]), axis=0)  # no crossing
        return {q: stacked[i] for i, q in enumerate(self.quantiles)}

    def _conformal_widen(self, h: int, cal: pd.DataFrame, cols: list[str]) -> float:
        """CQR: widen (or narrow) the outer quantiles so ~80% of calibration targets fall in."""
        lo_q, hi_q = min(self.quantiles), max(self.quantiles)
        if len(cal) < 100 or (h, lo_q) not in self.models:
            return 0.0
        pr = self._raw_quantiles(h, cal, cols)
        score = np.maximum(pr[lo_q] - cal["target"].to_numpy(), cal["target"].to_numpy() - pr[hi_q])
        level = hi_q - lo_q
        n = len(score)
        k = min(1.0, np.ceil((n + 1) * level) / n)
        return float(np.quantile(score, k))

    # --- forecasting --------------------------------------------------------------------------
    def latest_rows(self, run_date: date) -> pd.DataFrame:
        """Each series' latest feature row dated before run_date, if not too stale."""
        run_ts = pd.Timestamp(run_date)
        lo = self._dates.searchsorted(
            np.datetime64(run_ts - pd.Timedelta(days=self.max_staleness_days)), side="left")
        hi = self._dates.searchsorted(np.datetime64(run_ts), side="left")
        rows = self.features.iloc[lo:hi].drop_duplicates(KEYS, keep="last")
        rows = rows.assign(run_date=run_ts,
                           gap_days_to_run=(run_ts - rows["date"]).dt.days.astype(int))
        return rows

    def predict(self, history: pd.DataFrame, run_date: date, horizons: list[int]) -> pd.DataFrame:
        base = self.latest_rows(run_date)
        out = []
        for h in horizons:
            if (h, self.quantiles[0]) not in self.models or base.empty:
                continue
            x = base.assign(target_date=base["run_date"] + pd.Timedelta(days=h))
            x = add_target_calendar(x, self.calendar)
            cols = self.x_columns(x)
            pr = self._raw_quantiles(h, x, cols)
            lo_q, hi_q = min(self.quantiles), max(self.quantiles)
            pr[lo_q] = pr[lo_q] - self.widen.get(h, 0.0)
            pr[hi_q] = pr[hi_q] + self.widen.get(h, 0.0)
            res = pd.DataFrame({
                "commodity_id": x["commodity_id"].astype(str).to_numpy(),
                "province_id": x["province_id"].astype(int).to_numpy(),
                "horizon_days": h,
                "target_date": x["target_date"].to_numpy(),
            })
            last = np.exp(x["log_price"].to_numpy())
            for q in self.quantiles:
                res[_qcol(q)] = last * np.exp(pr[q])
            out.append(res)
        if not out:
            return pd.DataFrame(columns=[*KEYS, "horizon_days", "target_date",
                                         *map(_qcol, self.quantiles)])
        res = pd.concat(out, ignore_index=True)
        q = [_qcol(v) for v in self.quantiles]
        res[q] = np.sort(res[q].to_numpy(), axis=1)  # widening can't break the order
        return res
