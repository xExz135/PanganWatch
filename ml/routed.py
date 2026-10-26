"""LightGBM where it earned its place, the naive baseline elsewhere (owner decision 2026-10-26).

For each commodity and horizon, the fitted LightGBM is used only if its median forecast beat
"same as the last price" on the calibration half of the fold's validation slice, which ends
before the fold's cutoff, so the choice never sees the test window. Volatile commodities
(chilies, shallots) tend to pick LightGBM; administered or sticky ones (rice, oil, sugar)
tend to keep the baseline. Ranges come from whichever model is chosen.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

import pandas as pd

from ml.baselines import NaiveForecaster
from ml.lgbm import LGBMForecaster
from ml.settings import settings

KEYS = ["commodity_id", "province_id"]


@dataclass
class RoutedForecaster:
    model: LGBMForecaster
    baseline: NaiveForecaster = field(default_factory=NaiveForecaster)
    name: str = "lgbm_routed"
    # LightGBM must beat the baseline's validation MAE by at least this share
    min_gain: float = field(default_factory=lambda: settings()["routing"]["min_gain"])
    use_model: set = field(default_factory=set)  # {(commodity_id, horizon)} routed to model

    def fit(self, train: pd.DataFrame, valid: pd.DataFrame | None = None,
            horizons: list[int] | None = None) -> RoutedForecaster:
        model = self.model.fit(train, valid, horizons=horizons)
        baseline = self.baseline.fit(train, valid, horizons=horizons)
        return replace(self, model=model, baseline=baseline,
                       use_model=choose(model.validation, self.min_gain))

    def predict(self, history: pd.DataFrame, run_date: date, horizons: list[int]) -> pd.DataFrame:
        base = self.baseline.predict(history, run_date, horizons)
        if not self.use_model or base.empty:
            return base
        lgb = self.model.predict(history, run_date, horizons)
        routed = pd.Series([(c, h) in self.use_model
                            for c, h in zip(lgb["commodity_id"], lgb["horizon_days"], strict=True)],
                           index=lgb.index, dtype=bool)
        lgb = lgb[routed]
        # a series routed to the model but missing from its output keeps the baseline
        keep = base.merge(lgb[[*KEYS, "horizon_days"]], on=[*KEYS, "horizon_days"],
                          how="left", indicator=True)["_merge"].eq("left_only").to_numpy()
        return pd.concat([base[keep], lgb[base.columns]], ignore_index=True)


def choose(validation: dict, min_gain: float) -> set:
    """{(commodity_id, horizon)} where the model's validation MAE beat the baseline's."""
    out = set()
    for h, v in validation.items():
        better = v["mae_model"] < (1 - min_gain) * v["mae_naive"]
        out |= {(c, h) for c in v.loc[better, "commodity_id"]}
    return out
