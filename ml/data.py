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
    df = con.execute("""select date, is_ramadan, days_since_lebaran, days_to_lebaran,
                               is_holiday, day_of_week from dim_date""").df()
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_features(con, since=None) -> pd.DataFrame:
    """fct_features (DS, dbt/models/ml/): one row per published day x series, optionally only
    rows dated on or after `since` (the daily forecast needs just the latest rows)."""
    where, args = ("where date >= ?", [since]) if since is not None else ("", [])
    df = con.execute(f"select * from fct_features {where} "
                     "order by date, commodity_id, province_id", args).df()
    df["date"] = pd.to_datetime(df["date"])
    return df
