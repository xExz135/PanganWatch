"""Shared toy data for ml tests. `ml` is not an installed package, so put the repo root on
sys.path (CI runs plain `pytest`)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def toy_panel(start="2024-01-01", days=500, weekdays_only=True, seed=0) -> pd.DataFrame:
    """2 commodities x 2 provinces, a gentle trend plus noise, PIHPS-like weekday gaps."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=days, freq="D")
    if weekdays_only:
        dates = dates[dates.day_of_week < 5]
    rows = []
    for c, base in [("cabai_rawit_merah", 50000.0), ("beras_medium_1", 13000.0)]:
        for p in (31, 35):
            walk = np.cumsum(rng.normal(0, 0.01, len(dates)))
            y = base * np.exp(walk) * (1 + 0.0002 * np.arange(len(dates)))
            rows.append(pd.DataFrame({"date": dates, "commodity_id": c, "province_id": p,
                                      "y": np.round(y), "is_imputed": False}))
    return pd.concat(rows, ignore_index=True)


@pytest.fixture
def panel() -> pd.DataFrame:
    return toy_panel()
