"""Naive and seasonal-naive baselines with empirical 80% ranges.

Both copy a past price forward. Naive uses the last price before the run date; seasonal
naive uses the price one season (or a multiple) before the target date, never on or after
the run date. Their ranges come from how far that rule missed on the training data
(log-ratio quantiles per commodity and horizon), so the baselines get honest intervals too.
q50 is always the copied price itself, so the baseline stays a pure baseline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from ml.settings import settings


def _qcol(q: float) -> str:
    return f"q{round(q * 100)}"


@dataclass
class RuleForecaster:
    """Copy a past price forward. Subclasses define how far back from the target to look."""

    name: str = "rule"
    keys: list[str] = field(default_factory=lambda: list(settings()["target"]["series_keys"]))
    quantiles: list[float] = field(
        default_factory=lambda: list(settings()["backtest"]["quantiles"])
    )
    max_staleness_days: int = field(
        default_factory=lambda: settings()["baselines"]["max_staleness_days"]
    )
    # (group, horizon) -> {quantile: log-ratio}; group None = all commodities pooled
    residual_quantiles: dict = field(default_factory=dict)

    def lookback(self, horizon: int) -> int:
        """Days between the target date and the date whose price is copied (> horizon)."""
        raise NotImplementedError

    # --- training: learn the spread of this rule's misses --------------------------------
    def fit(self, train: pd.DataFrame, valid: pd.DataFrame | None = None,
            horizons: list[int] | None = None) -> RuleForecaster:
        horizons = horizons or list(settings()["backtest"]["horizons"])
        group = self.keys[0]
        wide = (train.assign(lp=np.log(train["y"]))
                .pivot_table(index="date", columns=self.keys, values="lp", aggfunc="last"))
        wide = wide.reindex(pd.date_range(wide.index.min(), wide.index.max(), freq="D"))
        carried = wide.ffill(limit=self.max_staleness_days)
        fitted = replace(self, residual_quantiles={})
        for h in horizons:
            resid = (wide - carried.shift(self.lookback(h))).stack(list(range(len(self.keys))))
            resid = resid.dropna()
            if resid.empty:
                continue
            for g, r in resid.groupby(level=group):
                fitted.residual_quantiles[(g, h)] = {
                    q: float(r.quantile(q)) for q in self.quantiles
                }
            fitted.residual_quantiles[(None, h)] = {
                q: float(resid.quantile(q)) for q in self.quantiles
            }
        return fitted

    # --- forecasting -------------------------------------------------------------------
    def predict(self, history: pd.DataFrame, run_date: date, horizons: list[int]) -> pd.DataFrame:
        run_ts = pd.Timestamp(run_date)
        hist = history
        if not hist["date"].is_monotonic_increasing:
            hist = hist.sort_values("date", kind="stable")
        dates = hist["date"].to_numpy()
        stale = pd.Timedelta(days=self.max_staleness_days)
        cols: dict[str, list] = {c: [] for c in [*self.keys, "horizon_days", "target_date",
                                                 *map(_qcol, self.quantiles)]}
        lasts: dict[pd.Timestamp, pd.DataFrame] = {}  # several horizons share a source date
        for h in horizons:
            target = run_ts + pd.Timedelta(days=h)
            source = target - pd.Timedelta(days=self.lookback(h))  # always < run_date
            if source not in lasts:
                # only the last `stale` days before the source date can supply a price
                lo = dates.searchsorted(np.datetime64(source - stale), side="left")
                hi = dates.searchsorted(np.datetime64(min(source, run_ts - pd.Timedelta(days=1))),
                                        side="right")
                lasts[source] = hist.iloc[lo:hi].drop_duplicates(self.keys, keep="last")
            last = lasts[source]
            if last.empty:
                continue
            y = last["y"].to_numpy(dtype=float)
            for k in self.keys:
                cols[k].append(last[k].to_numpy())
            cols["horizon_days"].append(np.full(len(last), h))
            cols["target_date"].append(np.full(len(last), np.datetime64(target, "ns")))
            groups = last[self.keys[0]].to_numpy()
            pooled = self.residual_quantiles.get((None, h), {})
            for q in self.quantiles:
                if q == 0.5:
                    cols[_qcol(q)].append(y)
                    continue
                shift = np.array([self.residual_quantiles.get((g, h), pooled).get(q, np.nan)
                                  for g in groups], dtype=float)
                cols[_qcol(q)].append(y * np.exp(shift))
        return pd.DataFrame({c: np.concatenate(v) if v else [] for c, v in cols.items()})


@dataclass
class NaiveForecaster(RuleForecaster):
    name: str = "naive"

    def lookback(self, horizon: int) -> int:
        # last price before the run date: run_date - 1 = target - (horizon + 1)
        return horizon + 1


@dataclass
class SeasonalNaiveForecaster(RuleForecaster):
    name: str = "seasonal_naive"
    season_days: int = field(default_factory=lambda: settings()["metrics"]["season_days"])

    def lookback(self, horizon: int) -> int:
        # the smallest whole number of seasons that lands before the run date
        return self.season_days * math.ceil((horizon + 1) / self.season_days)
