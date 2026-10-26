"""A2 asymmetric price transmission: do producer price rises reach the market faster or more
fully than falls?

PIHPS updates producer prices once a month (around the 25th; docs/source_notes.md), so the
spec's weekly regression would measure the update calendar, not transmission. This runs the
same split-lag regression on months instead:

    d ln retail[m] = a + sum_k b_up[k] * max(d ln producer[m-k], 0)
                       + sum_k b_dn[k] * min(d ln producer[m-k], 0) + e,   k = 0..LAGS

per commodity, pooled over provinces, with standard errors clustered by province. retail[m]
is the month's average traditional-market price; producer[m] is the producer figure in force
at the end of month m. Wald tests ask whether rises and falls pass through equally in total
(the spec's test) and within the same month (speed).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

LAGS = 2                 # months of lagged producer changes (0..LAGS)
MIN_PRODUCER_DAYS = 5    # days with a producer price for a province-month to count
MIN_RETAIL_DAYS = 10     # days with a retail price for a province-month to count
MIN_MONTHS = 24          # usable months for a province to join the pool
MIN_PROVINCES = 8        # provinces for a commodity to be estimated
ASYMMETRY_P = 0.05


def load_province_months(con, before=None) -> pd.DataFrame:
    """Province-month log prices from fct_margin_chain (DE gold), complete months only: the
    month containing `before` (default: no limit) and anything after it are left out."""
    df = con.execute(
        """
        with m as (
            select commodity_id, province_id, date_trunc('month', date) as month, date,
                   producer_price, retail_price
            from fct_margin_chain
            where retail_price is not null
              and (?::date is null or date < date_trunc('month', ?::date))
        )
        select commodity_id, province_id, month,
               ln(arg_max(producer_price, date) filter (where producer_price is not null))
                   as log_producer,
               avg(ln(retail_price)) as log_retail,
               count(*) filter (where producer_price is not null) as producer_days,
               count(*) as retail_days
        from m
        group by all
        """,
        [before, before],
    ).df()
    df = df[(df["producer_days"] >= MIN_PRODUCER_DAYS) & (df["retail_days"] >= MIN_RETAIL_DAYS)]
    df["month"] = pd.to_datetime(df["month"])
    return df.drop(columns=["producer_days", "retail_days"])


def design(province: pd.DataFrame, lags: int = LAGS) -> pd.DataFrame:
    """One province's monthly changes: y and split producer changes at lags 0..lags."""
    g = province.set_index("month").sort_index().asfreq("MS")
    dp = g["log_producer"].diff()
    out = pd.DataFrame({"y": g["log_retail"].diff()}, index=g.index)
    for k in range(lags + 1):
        out[f"up{k}"] = dp.clip(lower=0).shift(k)
        out[f"dn{k}"] = dp.clip(upper=0).shift(k)
    return out.dropna()


def fit_commodity(months: pd.DataFrame, lags: int = LAGS):
    """Fit one commodity. Returns (lag rows, summary dict) or None if too little data."""
    import statsmodels.api as sm

    parts = []
    for pid, g in months.groupby("province_id"):
        d = design(g, lags)
        if len(d) >= MIN_MONTHS:
            parts.append(d.assign(province_id=pid))
    if len(parts) < MIN_PROVINCES:
        return None
    df = pd.concat(parts)
    cols = [f"{d}{k}" for k in range(lags + 1) for d in ("up", "dn")]
    fit = sm.OLS(df["y"], sm.add_constant(df[cols])).fit(
        cov_type="cluster", cov_kwds={"groups": df["province_id"]})
    names = list(fit.params.index)
    r = np.zeros(len(names))
    for k in range(lags + 1):
        r[names.index(f"up{k}")] = 1.0
        r[names.index(f"dn{k}")] = -1.0
    p_equal = float(fit.wald_test(r.reshape(1, -1), scalar=True).pvalue)
    r0 = np.zeros(len(names))
    r0[names.index("up0")], r0[names.index("dn0")] = 1.0, -1.0
    p_same = float(fit.wald_test(r0.reshape(1, -1), scalar=True).pvalue)

    rows = []
    for direction, prefix in (("rise", "up"), ("fall", "dn")):
        cum = 0.0
        for k in range(lags + 1):
            b = float(fit.params[f"{prefix}{k}"])
            cum += b
            rows.append({"direction": direction, "lag_months": k, "coefficient": b,
                         "std_error": float(fit.bse[f"{prefix}{k}"]), "cumulative": cum})
    rise = [r_ for r_ in rows if r_["direction"] == "rise"]
    fall = [r_ for r_ in rows if r_["direction"] == "fall"]
    summary = {
        "n_provinces": len(parts),
        "n_obs": len(df),
        "rise_same_month": rise[0]["coefficient"],
        "fall_same_month": fall[0]["coefficient"],
        "rise_total": rise[-1]["cumulative"],
        "fall_total": fall[-1]["cumulative"],
        "p_value_equal_totals": p_equal,
        "p_value_equal_same_month": p_same,
        "is_asymmetric": p_equal < ASYMMETRY_P,
        "r_squared": float(fit.rsquared),
        "first_month": df.index.min().date(),
        "last_month": df.index.max().date(),
    }
    return rows, summary


def run(con, before=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """All commodities. Returns (lags table, summary table)."""
    months = load_province_months(con, before)
    lag_rows, summaries = [], []
    for cid, g in months.groupby("commodity_id"):
        res = fit_commodity(g)
        if res is None:
            continue
        rows, summary = res
        lag_rows += [{"commodity_id": cid, **r} for r in rows]
        summaries.append({"commodity_id": cid, **summary})
    return pd.DataFrame(lag_rows), pd.DataFrame(summaries)
