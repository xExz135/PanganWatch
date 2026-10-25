"""Forecast metrics. Inputs are array-likes; NaN pairs are dropped before scoring.

Conventions (TEAM.md §3.1): money in rupiah, percentages as decimals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _clean(*arrays) -> list[np.ndarray]:
    arrs = [np.asarray(a, dtype=float) for a in arrays]
    ok = np.ones(len(arrs[0]), dtype=bool)
    for a in arrs:
        ok &= ~np.isnan(a)
    return [a[ok] for a in arrs]


def mae(y_true, y_pred) -> float:
    """Mean absolute error, in the unit of the prices (Rp per kg or liter)."""
    y, p = _clean(y_true, y_pred)
    return float(np.mean(np.abs(y - p))) if len(y) else np.nan


def smape(y_true, y_pred) -> float:
    """Symmetric MAPE as a decimal in [0, 2]: mean of 2|y - p| / (|y| + |p|); 0/0 counts as 0."""
    y, p = _clean(y_true, y_pred)
    if not len(y):
        return np.nan
    denom = np.abs(y) + np.abs(p)
    ratio = np.divide(2 * np.abs(y - p), denom, out=np.zeros_like(denom), where=denom > 0)
    return float(np.mean(ratio))


def seasonal_naive_scale(series: pd.Series, season_days: int) -> float:
    """In-sample MAE of the seasonal-naive rule y(d) ~ y(d - m) on a date-indexed series.

    Only pairs where both d and d - m (calendar days) were observed count, so weekend and
    holiday gaps are skipped rather than filled. Returns NaN when no pair exists or the
    series never moved (scale 0 would make MASE infinite).
    """
    s = series.dropna()
    if s.empty:
        return np.nan
    s.index = pd.DatetimeIndex(s.index)
    lagged = s.copy()
    lagged.index = lagged.index + pd.Timedelta(days=season_days)
    diff = (s - lagged.reindex(s.index)).dropna()
    scale = float(np.mean(np.abs(diff))) if len(diff) else np.nan
    return scale if scale > 0 else np.nan


def mase(y_true, y_pred, scale) -> float:
    """Mean absolute scaled error. `scale` is one number or one per row (per-series scales)."""
    y, p, s = _clean(y_true, y_pred, np.broadcast_to(np.asarray(scale, float), np.shape(y_true)))
    return float(np.mean(np.abs(y - p) / s)) if len(y) else np.nan


def pinball(y_true, q_pred, alpha: float) -> float:
    """Pinball (quantile) loss for quantile level alpha, in price units."""
    y, q = _clean(y_true, q_pred)
    if not len(y):
        return np.nan
    diff = y - q
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def coverage(y_true, lower, upper) -> float:
    """Share of actuals inside [lower, upper], as a decimal."""
    y, lo, hi = _clean(y_true, lower, upper)
    return float(np.mean((y >= lo) & (y <= hi))) if len(y) else np.nan
