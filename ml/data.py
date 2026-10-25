"""Read the DE tables the forecaster needs. Read-only; nothing here corrects their data."""

from __future__ import annotations

import pandas as pd

from ml.settings import settings


def load_history(con, market_tier: str | None = None) -> pd.DataFrame:
    """Province prices for one market tier: series keys, date, y (rupiah), is_imputed."""
    tier = market_tier or settings()["target"]["market_tier"]
    df = con.execute(
        """
        select date, commodity_id, province_id, cast(price_idr as double) as y, is_imputed
        from fct_daily_price
        where market_tier = ?
        order by date, commodity_id, province_id
        """,
        [tier],
    ).df()
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_calendar(con) -> pd.DataFrame:
    df = con.execute("select date, is_ramadan, days_since_lebaran from dim_date").df()
    df["date"] = pd.to_datetime(df["date"])
    return df
