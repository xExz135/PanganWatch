"""Look-ahead check for anything computed "as of" a run date (features, forecasts).

`check_no_lookahead(fn, df, run_dates)` calls fn(df, run_date) three ways:
  1. on the full data,
  2. with every row dated >= run_date scrambled (values replaced by noise),
  3. with every row dated >= run_date removed.
fn must return only what is knowable at run_date, so all three results must be identical.
Any use of a future row (a centered window, shift(-1), a full-sample mean, a row count)
changes the output and raises LeakageError.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date

import numpy as np
import pandas as pd


class LeakageError(AssertionError):
    """fn(df, run_date) changed when only rows dated >= run_date changed."""


def _canonical(out) -> pd.DataFrame:
    frame = out.to_frame() if isinstance(out, pd.Series) else pd.DataFrame(out)
    frame = frame.reset_index(drop=False)
    return frame.sort_values(list(frame.columns)).reset_index(drop=True)


def check_no_lookahead(
    fn: Callable[[pd.DataFrame, date], pd.DataFrame | pd.Series],
    df: pd.DataFrame,
    run_dates: Iterable[date],
    *,
    date_col: str = "date",
    value_cols: list[str] | None = None,
    seed: int = 0,
) -> None:
    rng = np.random.default_rng(seed)
    cols = value_cols or [
        c for c in df.select_dtypes("number").columns if c != date_col
    ]
    dates = pd.to_datetime(df[date_col])
    for run_date in run_dates:
        future = dates >= pd.Timestamp(run_date)
        if not future.any():
            raise ValueError(f"no rows on or after {run_date}: the check would prove nothing")
        expected = _canonical(fn(df, run_date))

        scrambled = df.copy()
        for c in cols:
            noise = rng.uniform(0.1, 10.0, future.sum()) * (scrambled[c].abs().max() + 1.0)
            scrambled[c] = scrambled[c].astype(float)
            scrambled.loc[future, c] = noise
        truncated = df.loc[~future].copy()

        for label, variant in [("scrambled", scrambled), ("removed", truncated)]:
            got = _canonical(fn(variant, run_date))
            try:
                pd.testing.assert_frame_equal(got, expected, check_dtype=False)
            except AssertionError as err:
                raise LeakageError(
                    f"output for run_date {run_date} changed when rows dated >= run_date "
                    f"were {label}: it uses future data"
                ) from err
