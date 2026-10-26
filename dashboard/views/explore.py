"""Page 2 — Explore prices: how has this price moved? (spec §12)

Filters in one row; a line per market tier (fixed colors, direct end labels); a province
map colored by 7-day change; table view + CSV download.
"""

from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st
from common import (
    DIVERGING,
    TIER_COLORS,
    TIER_LABEL,
    TIER_ORDER,
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
    theme,
)

NATIONAL = 0  # pseudo province id for "all provinces"
DEFAULT_PROVINCE = 31  # DKI Jakarta, the persona's province
PERIODS = {"3 months": 91, "1 year": 365, "2 years": 730, "All": None}

page_header("Explore prices", "How has this price moved?")
latest = latest_price_date()
if latest is None:
    st.info("No price data loaded yet.")
    st.stop()

names = commodity_names()
provs = province_names()
mode = theme()

# --- one filter row scoping everything below --------------------------------------------
f1, f2, f3, f4 = st.columns([2, 2, 3, 1.4])
commodity = f1.selectbox(  # v1 commodities first; only those that exist in the data
    "Commodity", [c for c in V1_COMMODITIES if c in names]
    + sorted(c for c in names if c not in V1_COMMODITIES),
    format_func=names.get,
)
province_options = [NATIONAL, *provs]
province = f2.selectbox(
    "Province", province_options,
    format_func=lambda p: "All provinces (median)" if p == NATIONAL else provs[p],
    index=province_options.index(DEFAULT_PROVINCE) if DEFAULT_PROVINCE in provs else 0,
)
tiers = f3.multiselect("Market tiers", TIER_ORDER, default=TIER_ORDER,
                       format_func=TIER_LABEL.get)
period = f4.selectbox("Period", list(PERIODS), index=1)
days_back = PERIODS[period]
start = latest - timedelta(days=days_back) if days_back else date(2000, 1, 1)

if not tiers:
    st.info("Pick at least one market tier.")
    st.stop()

tier_marks = ", ".join("?" * len(tiers))
if province == NATIONAL:
    # days when under 80% of the usual provinces reported are dropped (holidays)
    series = query(f"""
        with daily as (
            select date, market_tier, median(price_idr) as price_idr, count(*) as n_provinces
            from fct_daily_price
            where commodity_id = ? and market_tier in ({tier_marks}) and date >= ?
            group by all
        )
        select * from daily
        qualify n_provinces >= 0.8 * median(n_provinces) over (partition by market_tier)
        order by date
    """, (commodity, *tiers, start))
else:
    series = query(f"""
        select date, market_tier, price_idr, n_cities
        from fct_daily_price
        where commodity_id = ? and province_id = ? and market_tier in ({tier_marks})
          and date >= ?
        order by date
    """, (commodity, province, *tiers, start))

place = "Indonesia (median of provinces)" if province == NATIONAL else provs[province]
unit = per_unit(commodity)

# --- line chart: title states the finding ----------------------------------------------
if series.empty:
    st.info(f"No {names[commodity]} prices for {place} in this period.")
else:
    headline_tier = "traditional" if "traditional" in tiers else tiers[0]
    h = series[series["market_tier"] == headline_tier]
    if len(h) >= 2:
        change = h["price_idr"].iloc[-1] / h["price_idr"].iloc[0] - 1
        word = "rose" if change > 0.005 else "fell" if change < -0.005 else "held steady"
        title = (f"{names[commodity]} in {place}: {TIER_LABEL[headline_tier].lower()} price "
                 f"{word} {pct(abs(change), signed=False) if word != 'held steady' else ''} "
                 f"since {h['date'].iloc[0]:%b %Y}, now {rupiah(h['price_idr'].iloc[-1])} {unit}")
    else:
        title = f"{names[commodity]} in {place}"

    fig = go.Figure()
    for tier in TIER_ORDER:  # fixed order + fixed color per tier
        t = series[series["market_tier"] == tier]
        if t.empty:
            continue
        color = TIER_COLORS[mode][tier]
        fig.add_trace(go.Scatter(
            x=t["date"], y=t["price_idr"], name=TIER_LABEL[tier], mode="lines",
            line={"color": color, "width": 2},
            hovertemplate="%{x|%d %b %Y}<br>" + TIER_LABEL[tier] + ": Rp %{y:,.0f}<extra></extra>",
        ))
        last = t.iloc[-1]  # direct label at the line end (selective, not every point)
        fig.add_annotation(
            x=last["date"], y=last["price_idr"], text=f" {TIER_LABEL[tier]}",
            showarrow=False, xanchor="left", font={"size": 12}, xshift=4,
        )
    fig.update_layout(
        title={"text": title, "font": {"size": 15}}, height=420,
        margin={"l": 10, "r": 130, "t": 60, "b": 10}, hovermode="x unified",
        legend={"orientation": "h", "y": -0.12},
        yaxis={"title": f"Rupiah {unit}", "tickformat": ",.0f", "rangemode": "tozero"},
        xaxis={"title": None},
    )
    st.plotly_chart(fig, theme="streamlit", width="stretch")
    if province != NATIONAL and "n_cities" in series:
        thin = series.loc[series["market_tier"] == headline_tier, "n_cities"].median()
        if thin <= 1:
            st.caption(f"⚠️ {place} has one reporting city for this tier, so day-to-day "
                       "moves can be noisy.")

# --- map: where is it moving? ----------------------------------------------------------
st.subheader("Across provinces")
map_df = query("""
    select c.province_id, p.name, p.lat, p.lon, c.price_idr, c.chg_7d_pct, c.date
    from fct_price_change as c
    join dim_province as p using (province_id)
    where c.commodity_id = ? and c.market_tier = 'traditional' and c.date > ?::date - 7
    qualify c.date = max(c.date) over (partition by c.province_id)
""", (commodity, latest))
if map_df.empty:
    st.info("No recent traditional-market prices for this commodity.")
else:
    top = map_df.sort_values("price_idr", ascending=False).iloc[0]
    low = map_df.sort_values("price_idr").iloc[0]
    m = map_df.dropna(subset=["chg_7d_pct"])
    bound = max(0.05, float(m["chg_7d_pct"].abs().quantile(0.95))) if not m.empty else 0.1
    mapfig = go.Figure(go.Scattergeo(
        lat=map_df["lat"], lon=map_df["lon"], mode="markers",
        marker={
            # 2px ring in the surface color, so overlapping dots stay separate
            "size": 14, "line": {"width": 2,
                                 "color": "#1a1a19" if mode == "dark" else "#fcfcfb"},
            "color": map_df["chg_7d_pct"].fillna(0), "cmin": -bound, "cmax": bound,
            "colorscale": [[i / 4, c] for i, c in enumerate(DIVERGING[mode])],
            "colorbar": {"title": "7-day<br>change", "tickformat": "+.0%"},
        },
        customdata=list(zip(map_df["name"], map_df["price_idr"].map(rupiah),
                            map_df["chg_7d_pct"].map(pct), strict=True)),
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]} " + unit
                      + "<br>7-day: %{customdata[2]}<extra></extra>",
    ))
    mapfig.update_geos(
        projection_type="mercator", lataxis_range=[-11.5, 6.5], lonaxis_range=[94, 142],
        showland=True, landcolor="rgba(137,135,129,0.15)", showcountries=False,
        showocean=False, showlakes=False, bgcolor="rgba(0,0,0,0)",
    )
    mapfig.update_layout(
        title={"text": f"Highest: {top['name']} at {rupiah(top['price_idr'])}; lowest: "
                       f"{low['name']} at {rupiah(low['price_idr'])} ({unit}, traditional market)",
               "font": {"size": 15}},
        height=420, margin={"l": 0, "r": 0, "t": 50, "b": 0},
    )
    st.plotly_chart(mapfig, theme="streamlit", width="stretch")
    st.caption("Dot color = change over 7 days (blue cheaper, red more expensive, gray flat). "
               "One dot per province, at its capital.")

# --- table view + download -------------------------------------------------------------
with st.expander("Table view and download"):
    if not series.empty:
        out = series.assign(
            commodity=names[commodity], place=place,
            market_tier=series["market_tier"].map(TIER_LABEL),
        )
        st.dataframe(
            out.assign(price=out["price_idr"].map(rupiah)).drop(columns=["price_idr"]),
            hide_index=True, width="stretch",
        )
        st.download_button(
            "Download CSV", out.to_csv(index=False).encode("utf-8"),
            file_name=f"panganwatch_{commodity}_{place.split(' ')[0].lower()}.csv",
            mime="text/csv",
        )

footer()
