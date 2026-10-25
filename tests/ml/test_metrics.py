"""Metric functions on toy numbers worked out by hand."""

import math

import numpy as np
import pandas as pd
import pytest

from ml import metrics


def test_mae_in_price_units():
    assert metrics.mae([100, 200], [110, 190]) == 10


def test_smape_decimal_and_zero_pair():
    assert metrics.smape([100], [110]) == pytest.approx(20 / 210)
    assert metrics.smape([0, 100], [0, 100]) == 0  # 0/0 counts as a perfect forecast


def test_nan_pairs_are_dropped():
    assert metrics.mae([100, np.nan, 300], [110, 5, np.nan]) == 10
    assert math.isnan(metrics.mae([np.nan], [1]))


def test_mase_scalar_and_per_row_scale():
    assert metrics.mase([10, 20], [12, 18], 2) == 1
    assert metrics.mase([10, 20], [12, 18], [1, 2]) == pytest.approx((2 / 1 + 2 / 2) / 2)


def test_pinball_asymmetry():
    assert metrics.pinball([10], [8], 0.9) == pytest.approx(1.8)    # under-forecast: costly
    assert metrics.pinball([10], [12], 0.9) == pytest.approx(0.2)   # over-forecast: cheap
    assert metrics.pinball([10, 20], [12, 17], 0.5) == pytest.approx(
        0.5 * metrics.mae([10, 20], [12, 17]))


def test_coverage_counts_bounds_as_inside():
    assert metrics.coverage([1, 6, 10], [0, 0, 0], [6, 6, 6]) == pytest.approx(2 / 3)


def test_seasonal_scale_skips_weekend_gaps():
    # value = day number, weekdays only: every observed (d, d-7) pair differs by exactly 7
    dates = pd.date_range("2025-01-06", periods=60, freq="D")
    s = pd.Series(np.arange(60.0), index=dates)
    s = s[s.index.day_of_week < 5]
    assert metrics.seasonal_naive_scale(s, 7) == 7


def test_seasonal_scale_flat_series_is_nan():
    s = pd.Series(5.0, index=pd.date_range("2025-01-01", periods=30, freq="D"))
    assert math.isnan(metrics.seasonal_naive_scale(s, 7))
