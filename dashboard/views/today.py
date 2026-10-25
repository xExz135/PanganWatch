"""Page 1 — Today: what needs attention today? (spec §12)

Phase 1 version: national price cards and a rule-based watch list using the spec's
alert rules that need no model (High: 7-day change > 20 %; Watch: price > 2 SD above
its 28-day mean). Phase 4 adds model spike risks and today's buy recommendations.
"""

import pandas as pd
import streamlit as st
from common import (
    V1_COMMODITIES,
    commodity_names,
    footer,
    latest_price_date,
    page_header,
    pct,
    per_unit,
    province_names,
    query,
    rupiah,
    short_names,
)

HIGH_CHANGE = 0.20     # spec §12: high alert when the 7-day change exceeds 20 %
WATCH_ZSCORE = 2.0     # spec §12: watch when price > 2 SD above its 28-day mean

page_header("Today", "What needs attention today?")

latest = latest_price_date()
if latest is None:
    st.info("No price data loaded yet.")
    st.stop()

names = commodity_names()
ids = tuple(V1_COMMODITIES)
marks = ", ".join("?" * len(ids))

# National price = median of province prices (traditional market) on each day.
national = query(f"""
    select date, commodity_id, median(price_idr) as price, count(*) as provinces
    from fct_daily_price
    where market_tier = 'traditional' and commodity_id in ({marks})
      and date >= ?::date - 70
    group by all
    order by date
""", (*ids, latest))

st.subheader(f"National prices on {latest:%d %b %Y}")
st.caption("Median of province prices in traditional markets. Arrow = change vs 7 days earlier; "
           "red means more expensive for a buyer.")

cards = []
for cid in V1_COMMODITIES:
    s = national[national["commodity_id"] == cid].set_index("date")["price"]
    if s.empty:
        continue
    now_date = s.index.max()
    week_ago = s[s.index <= now_date - pd.Timedelta(days=7)]
    change = s.iloc[-1] / week_ago.iloc[-1] - 1 if not week_ago.empty else None
    cards.append((cid, s, change))

short = short_names()
cols: list = []
for i, (cid, s, change) in enumerate(cards):
    if i % 4 == 0:  # one st.columns per row, so phones stack cards in reading order
        cols = st.columns(4)
    n_prov = int(national.loc[(national.commodity_id == cid)
                              & (national.date == s.index.max()), "provinces"].iloc[0])
    flat = change is not None and abs(change) < 0.0005
    with cols[i % 4]:
        st.metric(
            label=short[cid],
            value=rupiah(s.iloc[-1]),
            delta=("no change" if flat else pct(change)) if change is not None else None,
            # price up = worse for a buyer, so up is red; no change is neutral gray
            delta_color="off" if flat else "inverse",
            delta_arrow="off" if flat else "auto",
            help=f"{names[cid]}, {per_unit(cid)}. Median of {n_prov} provinces. "
                 "Line: last 60 published days.",
            chart_data=s.tail(60).tolist(),
            chart_type="line",
            border=True,
        )

# --- watch list -------------------------------------------------------------------------
alerts = query(f"""
    with recent as (
        select *
        from fct_price_change
        where market_tier = 'traditional' and commodity_id in ({marks})
          and date > ?::date - 7
        qualify date = max(date) over (partition by commodity_id, province_id)
    )
    select date, commodity_id, province_id, price_idr, chg_7d_pct, zscore_28d
    from recent
    where chg_7d_pct > ? or zscore_28d > ?
""", (*ids, latest, HIGH_CHANGE, WATCH_ZSCORE))

st.subheader("Watch list")
if alerts.empty:
    st.success("✅ No province has a commodity up more than 20% in a week or unusually "
               "high for its last 28 days.")
else:
    provs = province_names()
    alerts["level"] = alerts["chg_7d_pct"].gt(HIGH_CHANGE).map({True: "🔴 High", False: "🟠 Watch"})
    alerts = alerts.sort_values(["level", "chg_7d_pct"], ascending=[True, False])
    n_high = (alerts["level"] == "🔴 High").sum()
    st.caption(
        f"**{n_high} high** and **{len(alerts) - n_high} watch** alerts across "
        f"{alerts['province_id'].nunique()} provinces. High = up more than 20% in 7 days; "
        "Watch = more than 2 standard deviations above the 28-day average. "
        "Model-based spike risk arrives in Phase 4."
    )
    top = alerts.head(5)
    for r in top.itertuples():
        # spec §12 message format
        st.markdown(
            f"{r.level} — **{names[r.commodity_id]}, {provs[r.province_id]}**: "
            f"{pct(r.chg_7d_pct)} in 7 days. "
            f"Current {rupiah(r.price_idr)} {per_unit(r.commodity_id)}."
        )
    with st.expander(f"All {len(alerts)} alerts (table)"):
        st.dataframe(
            pd.DataFrame({
                "Level": alerts["level"],
                "Commodity": alerts["commodity_id"].map(names),
                "Province": alerts["province_id"].map(provs),
                "Price": alerts["price_idr"].map(rupiah),
                "7-day change": alerts["chg_7d_pct"].map(pct),
                "vs 28-day mean (SD)": alerts["zscore_28d"].round(1),
                "As of": alerts["date"].dt.strftime("%d %b %Y"),
            }),
            hide_index=True, width="stretch",
        )

footer()
