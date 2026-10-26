"""Insights: what do five years of prices say? One tab per analysis (spec Phase 2).

A5 Lebaran & Ramadan effects reads ana_a5_lebaran_phases / ana_a5_lebaran_curve
(dbt/models/analyses/). Other analyses get a tab when their tables exist.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from common import (
    DIVERGING,
    SEQUENTIAL_BLUE,
    TIER_COLORS,
    V1_COMMODITIES,
    commodity_names,
    footer,
    page_header,
    province_names,
    query,
    rupiah,
    short_names,
    table_exists,
    theme,
)

page_header("Insights", "What do five years of prices tell a buyer?")
mode = theme()
names = commodity_names()
short = short_names()


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def share(v: float) -> str:
    """0.999 -> '99.9%': never round a near-total up to 100%."""
    return f"{v:.1%}" if 0.995 <= v < 1 else f"{v:.0%}"


def change(index_value: float) -> str:
    """Index 134.8 -> '+35%' (vs the price trend)."""
    return f"{index_value - 100:+.0f}%"


def lebaran_tab() -> None:
    if not (table_exists("ana_a5_lebaran_phases") and table_exists("ana_a5_lebaran_curve")):
        st.info("This analysis appears after the next data update.")
        return
    marks = ", ".join("?" * len(V1_COMMODITIES))
    phases = query(f"""
        select commodity_id, phase_order, phase, index_median, index_min, index_max, n_years
        from ana_a5_lebaran_phases where commodity_id in ({marks}) order by phase_order
    """, tuple(V1_COMMODITIES))
    years = query("select min(lebaran_year) as y0, max(lebaran_year) as y1, "
                  "count(distinct lebaran_year) as n from ana_a5_lebaran_daily")
    if phases.empty:
        st.info("Not enough price history around Lebaran yet.")
        return
    y0, y1, n_years = (int(v) for v in years.iloc[0])
    span = f"median of {n_years} Lebarans, {y0}–{y1}"

    st.markdown(
        "**Question:** when do prices rise around Ramadan and Lebaran, and when do they come "
        "back down? A buyer who knows the timing can stock up before the rise instead of "
        "during it."
    )

    # --- overview: every commodity x phase ---------------------------------------------
    order = [c for c in V1_COMMODITIES if c in set(phases["commodity_id"])]
    grid = phases.pivot(index="commodity_id", columns="phase_order", values="index_median")
    grid = grid.reindex(order)
    labels = phases.drop_duplicates("phase_order").set_index("phase_order")["phase"]
    z = grid.to_numpy() - 100
    heat = go.Figure(go.Heatmap(
        z=z, x=[labels[p] for p in grid.columns], y=[short.get(c, c) for c in grid.index],
        zmid=0, zmin=-35, zmax=35,
        colorscale=[[i / (len(DIVERGING[mode]) - 1), c] for i, c in enumerate(DIVERGING[mode])],
        text=[[f"{v:+.0f}%" for v in row] for row in z], texttemplate="%{text}",
        xgap=2, ygap=2,
        colorbar={"title": "vs trend", "ticksuffix": "%"},
        hovertemplate="%{y}, %{x}<br>%{z:+.1f}% vs the price trend<extra></extra>",
    ))
    heat.update_layout(
        title={"text": "Chilies peak as Ramadan starts, shallots keep rising after Lebaran, "
                       "rice and bulk oil barely move", "font": {"size": 15}},
        height=420, margin={"l": 10, "r": 10, "t": 60, "b": 10},
        yaxis={"autorange": "reversed"}, xaxis={"side": "bottom"},
    )
    st.plotly_chart(heat, theme="streamlit", width="stretch")
    st.caption(f"National traditional-market price vs its own 12-month trend, {span}. "
               "Ramadan starts 29–30 days before Lebaran. Red = above trend, blue = below.")

    # --- detail: one commodity, median curve + range across years ----------------------
    commodity = st.selectbox("Commodity", order, format_func=lambda c: names.get(c, c),
                             key="a5_commodity")
    curve = query("""select event_day, index_median, index_min, index_max, n_years
                     from ana_a5_lebaran_curve where commodity_id = ? order by event_day""",
                  (commodity,))
    p = phases[phases["commodity_id"] == commodity].set_index("phase_order")
    title = (f"{short.get(commodity, commodity)}: {change(p.loc[3, 'index_median'])} in "
             f"Ramadan's first week, {change(p.loc[5, 'index_median'])} in the last week before "
             f"Lebaran, {change(p.loc[7, 'index_median'])} 2–4 weeks after")
    color = TIER_COLORS[mode]["traditional"]
    fig = go.Figure()
    fig.add_vrect(x0=-30, x1=-0.5, fillcolor="gray", opacity=0.08, line_width=0,
                  annotation_text="Ramadan", annotation_position="top left")
    fig.add_vline(x=0, line={"color": "gray", "width": 1, "dash": "dot"},
                  annotation_text="Lebaran", annotation_position="top right")
    fig.add_hline(y=100, line={"color": "gray", "width": 1, "dash": "dash"})
    fig.add_trace(go.Scatter(
        x=curve["event_day"], y=curve["index_max"], mode="lines", line={"width": 0},
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=curve["event_day"], y=curve["index_min"], mode="lines", line={"width": 0},
        fill="tonexty", fillcolor=rgba(color, 0.2), name="Range across years",
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=curve["event_day"], y=curve["index_median"], mode="lines+markers",
        line={"color": color, "width": 2}, marker={"size": 4}, name="Median year",
        customdata=curve[["index_min", "index_max", "n_years"]],
        hovertemplate=("Day %{x} from Lebaran<br>Median %{y:.0f} "
                       "(range %{customdata[0]:.0f}–%{customdata[1]:.0f}, "
                       "%{customdata[2]} years)<extra></extra>"),
    ))
    fig.update_layout(
        title={"text": title, "font": {"size": 15}}, height=420,
        margin={"l": 10, "r": 10, "t": 60, "b": 10},
        legend={"orientation": "h", "y": -0.18},
        xaxis={"title": "Days from Lebaran", "range": [-61, 31]},
        yaxis={"title": "Index (100 = trend two months before)"},
    )
    st.plotly_chart(fig, theme="streamlit", width="stretch")

    with st.expander("Table view"):
        t = p.reset_index()[["phase", "index_median", "index_min", "index_max", "n_years"]]
        for col in ["index_median", "index_min", "index_max"]:
            t[col] = t[col].map(change)
        st.dataframe(t.rename(columns={
            "phase": "Phase", "index_median": "Median year", "index_min": "Lowest year",
            "index_max": "Highest year", "n_years": "Years"}), hide_index=True)

    st.markdown(
        "**How it's measured.** For each Lebaran, the national price (median across "
        "provinces) is divided by its 12-month rolling median, so slow inflation is not "
        "counted as a Lebaran effect, then set to 100 two months before Lebaran. The line is "
        "the median year; the band is the lowest and highest year. PIHPS publishes on "
        "weekdays only, so the Lebaran holiday week has gaps."
    )


def volatility_tab() -> None:
    if not table_exists("ana_a6_volatility"):
        st.info("This analysis appears after the next data update.")
        return
    vol = query("""select geo_level, commodity_id, province_id, spike_share, spike_days, n_days,
                          volatility_daily, volatility_90d, median_reporting, is_thin,
                          risk_segment
                   from ana_a6_volatility""")
    nat = vol[vol["geo_level"] == "national"].sort_values("spike_share")
    if nat.empty:
        st.info("Not enough price history yet.")
        return
    st.markdown(
        "**Question:** which foods can jump in price suddenly, and where? A buyer facing a "
        "likely jump can stock up early; a stable food can be bought as needed."
    )
    color = TIER_COLORS[mode]["traditional"]
    rising = nat[nat["spike_share"] >= 0.01]
    never = nat[nat["spike_days"] == 0]
    title = (f"Nationally, only {len(rising)} of {len(nat)} foods jumped 15%+ within two "
             f"weeks on more than 1% of days; {len(never)} never did")
    bars = go.Figure(go.Bar(
        x=nat["spike_share"], y=[short.get(c, c) for c in nat["commodity_id"]],
        orientation="h", marker={"color": color},
        text=[f"{v:.0%}" if v >= 0.005 else "0%" for v in nat["spike_share"]],
        textposition="outside", cliponaxis=False,
        customdata=nat[["spike_days", "n_days"]],
        hovertemplate=("%{y}: a 15%+ rise within 14 days followed %{x:.1%} of days "
                       "(%{customdata[0]} of %{customdata[1]})<extra></extra>"),
    ))
    bars.update_layout(
        title={"text": title, "font": {"size": 15}}, height=max(420, 24 * len(nat)),
        margin={"l": 10, "r": 40, "t": 60, "b": 10},
        xaxis={"title": "Share of days followed by a 15%+ rise within 14 days",
               "tickformat": ".0%"},
        bargap=0.3,
    )
    st.plotly_chart(bars, theme="streamlit", width="stretch")
    st.caption("National traditional-market price (median across provinces), 2022 to today.")

    # --- one commodity across provinces -------------------------------------------------
    prov = vol[(vol["geo_level"] == "province") & ~vol["is_thin"]]
    choices = [c for c in nat.sort_values("spike_share", ascending=False)["commodity_id"]
               if c in set(prov["commodity_id"])]
    commodity = st.selectbox("Commodity", choices, format_func=lambda c: names.get(c, c),
                             key="a6_commodity")
    pnames = province_names()
    g = prov[prov["commodity_id"] == commodity].sort_values("spike_share")
    national_share = float(nat.loc[nat["commodity_id"] == commodity, "spike_share"].iloc[0])
    top, low = g.iloc[-1], g.iloc[0]
    title = (f"{short.get(commodity, commodity)}: from {low['spike_share']:.0%} of days in "
             f"{pnames[low['province_id']]} to {top['spike_share']:.0%} in "
             f"{pnames[top['province_id']]} (median province {g['spike_share'].median():.0%})")
    pfig = go.Figure(go.Bar(
        x=g["spike_share"], y=[pnames[p] for p in g["province_id"]], orientation="h",
        marker={"color": color}, name="Province",
        hovertemplate="%{y}: %{x:.1%} of days<extra></extra>",
    ))
    pfig.add_vline(x=national_share, line={"color": "gray", "width": 1, "dash": "dash"},
                   annotation_text=f"National {national_share:.0%}",
                   annotation_position="top")
    pfig.update_layout(
        title={"text": title, "font": {"size": 15}}, height=max(420, 22 * len(g)),
        margin={"l": 10, "r": 10, "t": 60, "b": 10},
        xaxis={"title": "Share of days followed by a 15%+ rise within 14 days",
               "tickformat": ".0%"},
        yaxis={"tickmode": "array", "tickvals": [pnames[p] for p in g["province_id"]]},
        bargap=0.3,
    )
    st.plotly_chart(pfig, theme="streamlit", width="stretch")
    n_thin = int(vol[(vol["geo_level"] == "province") & vol["is_thin"]
                     & (vol["commodity_id"] == commodity)].shape[0])
    if n_thin:
        st.caption(f"{n_thin} provinces with only one reporting city are left out: one "
                   "market's swings are not a province's.")

    with st.expander("Table view"):
        t = nat.sort_values("spike_share", ascending=False)
        st.dataframe(pd.DataFrame({
            "Commodity": [names.get(c, c) for c in t["commodity_id"]],
            "Risk": t["risk_segment"].str.capitalize(),
            "Days with a 15%+ jump ahead": t["spike_share"].map(lambda v: f"{v:.1%}"),
            "Typical daily move": t["volatility_daily"].map(lambda v: f"{v:.2%}"),
            "Daily move, last 90 days": t["volatility_90d"].map(lambda v: f"{v:.2%}"),
        }), hide_index=True)
    st.markdown(
        "**How it's measured.** For every day, did the price rise 15% or more at some point in "
        "the next 14 days? The share of such days is the jump risk; high means 10% or more of "
        "days, medium 1–10%, low under 1%. The typical daily move is the standard deviation of "
        "day-to-day price changes."
    )


def margins_tab() -> None:
    if not (table_exists("ana_a1_margins_summary") and table_exists("ana_a1_margins_monthly")):
        st.info("This analysis appears after the next data update.")
        return
    summ = query("""select commodity_id, producer_share, wholesale_share, median_provinces,
                           is_thin, producer_share_first_12m, producer_share_last_12m
                    from ana_a1_margins_summary""")
    ok = summ[~summ["is_thin"]].sort_values("producer_share", ascending=False)
    if ok.empty:
        st.info("Not enough matched producer, wholesale and retail prices yet.")
        return
    st.markdown(
        "**Question:** of what a shopper pays at a traditional market, how much is the "
        "producer price, and how much goes to traders and retailers?"
    )
    tiers = TIER_COLORS[mode]
    ylab = [short.get(c, c) for c in ok["commodity_id"]]
    parts = [
        ("Producer price", ok["producer_share"], tiers["producer"]),
        ("Producer → wholesale", (ok["wholesale_share"] - ok["producer_share"]).clip(lower=0),
         tiers["wholesale"]),
        ("Wholesale → market", 1 - ok["wholesale_share"], tiers["traditional"]),
    ]
    fig = go.Figure()
    for label, values, color in parts:
        fig.add_trace(go.Bar(
            x=values * 100, y=ylab, orientation="h", name=label, marker={"color": color},
            hovertemplate="%{y}<br>" + label + ": Rp %{x:.0f} of every Rp 100<extra></extra>",
        ))
    fresh = ok[ok["commodity_id"].isin(["cabai_rawit_merah", "cabai_merah_keriting",
                                        "cabai_merah_besar", "cabai_rawit_hijau",
                                        "bawang_merah"])]["producer_share"]
    staple = ok[ok["commodity_id"].isin(["beras_medium_1", "telur_ayam_ras",
                                         "daging_sapi_1"])]["producer_share"]
    if not fresh.empty and not staple.empty:
        title = (f"Producers get Rp {fresh.min() * 100:.0f}–{fresh.max() * 100:.0f} of every "
                 f"Rp 100 paid for chilies and shallots, Rp {staple.min() * 100:.0f}–"
                 f"{staple.max() * 100:.0f} for rice, eggs and beef")
    else:
        title = "Producer price as a share of the market price"
    fig.update_layout(
        barmode="stack", title={"text": title, "font": {"size": 15}},
        height=max(420, 24 * len(ok)), margin={"l": 10, "r": 10, "t": 60, "b": 10},
        xaxis={"title": "Rupiah of every Rp 100 paid at a traditional market",
               "range": [0, 100]},
        yaxis={"autorange": "reversed"}, legend={"orientation": "h", "y": -0.12},
        bargap=0.3,
    )
    st.plotly_chart(fig, theme="streamlit", width="stretch")
    thin = summ[summ["is_thin"]]
    if not thin.empty:
        st.caption("Left out, producer prices from fewer than 10 provinces: "
                   + ", ".join(short.get(c, c) for c in thin["commodity_id"]) + ".")

    options = list(ok["commodity_id"])
    commodity = st.selectbox("Commodity", options, format_func=lambda c: names.get(c, c),
                             index=options.index("beras_medium_1")
                             if "beras_medium_1" in options else 0, key="a1_commodity")
    monthly = query("""select month, producer_share, wholesale_share, n_provinces
                       from ana_a1_margins_monthly where commodity_id = ? order by month""",
                    (commodity,))
    row = ok[ok["commodity_id"] == commodity].iloc[0]
    first, last = row["producer_share_first_12m"], row["producer_share_last_12m"]
    word = "rose" if last - first > 0.01 else "fell" if first - last > 0.01 else "held at"
    title = (f"{short.get(commodity, commodity)}: producer share {word} "
             + (f"from {first:.0%} to {last:.0%}" if word != "held at" else f"{last:.0%}")
             + " (first vs last 12 months)")
    line = go.Figure()
    for col, label, color in [("producer_share", "Producer price", tiers["producer"]),
                              ("wholesale_share", "Wholesale price", tiers["wholesale"])]:
        line.add_trace(go.Scatter(
            x=monthly["month"], y=monthly[col], name=label, mode="lines",
            line={"color": color, "width": 2},
            customdata=monthly["n_provinces"],
            hovertemplate=("%{x|%b %Y}<br>" + label + ": %{y:.0%} of the market price "
                           "(%{customdata} provinces)<extra></extra>"),
        ))
    line.update_layout(
        title={"text": title, "font": {"size": 15}}, height=380,
        margin={"l": 10, "r": 10, "t": 60, "b": 10}, hovermode="x unified",
        yaxis={"title": "Share of the market price", "tickformat": ".0%"},
        legend={"orientation": "h", "y": -0.15},
    )
    st.plotly_chart(line, theme="streamlit", width="stretch")

    with st.expander("Table view"):
        t = summ.sort_values("producer_share", ascending=False)
        st.dataframe(pd.DataFrame({
            "Commodity": [names.get(c, c) for c in t["commodity_id"]],
            "Producer share": t["producer_share"].map(lambda v: f"{v:.0%}"),
            "Wholesale share": t["wholesale_share"].map(lambda v: f"{v:.0%}"),
            "First 12 months": t["producer_share_first_12m"].map(lambda v: f"{v:.0%}"),
            "Last 12 months": t["producer_share_last_12m"].map(lambda v: f"{v:.0%}"),
            "Provinces (typical month)": t["median_provinces"].astype(int),
        }), hide_index=True)
    st.markdown(
        "**How it's measured.** Only province-days with all three prices (producer, wholesale, "
        "traditional market) count. Each month takes the median of the same-day, "
        "same-province ratios, and the chart shows the median month since 2022. Single days "
        "and single provinces are too noisy: PIHPS producer and wholesale prices often cross "
        "locally. \"Producer\" is PIHPS's producer tier, which for rice is milled rice at the "
        "producer level, not the farmer's unhusked grain."
    )


def compliance_tab() -> None:
    needed = ["ana_a4_compliance_regulation", "ana_a4_compliance_province",
              "ana_a4_compliance_monthly"]
    if not all(table_exists(t) for t in needed):
        st.info("This analysis appears after the next data update.")
        return
    regs = query("""select commodity_id, regulation, price_type, first_date, last_date,
                           n_provinces, share_above, median_excess_when_above,
                           n_provinces_mostly_above, reference_min_idr, reference_max_idr,
                           source_kind, source_url
                    from ana_a4_compliance_regulation where market_tier = 'traditional'""")
    if regs.empty:
        st.info("No reference prices overlap the price history yet.")
        return
    st.markdown(
        "**Question:** do traditional-market prices stay under the government's ceiling (HET) "
        "and reference prices (HAP)? Each regulation is cited with its source below."
    )
    # the regulation in force most recently, per commodity
    latest = (regs.sort_values("first_date").groupby("commodity_id").tail(1)
              .sort_values("share_above"))
    labels = [f"{short.get(r.commodity_id, r.commodity_id)} ({r.price_type})"
              for r in latest.itertuples()]
    rice = latest[latest["commodity_id"] == "beras_medium_1"]
    if not rice.empty:
        r = rice.iloc[0]
        title = (f"Medium rice sold above its ceiling on {share(r['share_above'])} of "
                 f"province-days since {pd.Timestamp(r['first_date']):%b %Y}, in "
                 f"{int(r['n_provinces_mostly_above'])} of {int(r['n_provinces'])} provinces")
    else:
        title = "Share of province-days above the reference price, latest regulation"
    color = TIER_COLORS[mode]["traditional"]
    bars = go.Figure(go.Bar(
        x=latest["share_above"], y=labels, orientation="h", marker={"color": color},
        text=[share(v) for v in latest["share_above"]], textposition="outside",
        cliponaxis=False,
        customdata=latest[["regulation", "median_excess_when_above"]],
        hovertemplate=("%{y}: above on %{x:.0%} of province-days<br>%{customdata[0]}"
                       "<br>median %{customdata[1]:.0%} above when above<extra></extra>"),
    ))
    bars.update_layout(
        title={"text": title, "font": {"size": 15}}, height=max(380, 34 * len(latest)),
        margin={"l": 10, "r": 40, "t": 60, "b": 10}, bargap=0.3,
        xaxis={"title": "Share of province-days above, latest regulation", "tickformat": ".0%",
               "range": [0, 1.08]},
    )
    st.plotly_chart(bars, theme="streamlit", width="stretch")
    st.caption("HET = harga eceran tertinggi (a legal ceiling); HAP = harga acuan penjualan "
               "(a reference price; its upper bound is used). Traditional markets. Bulk oil's "
               "ceiling ended in Aug 2024.")

    # --- one commodity: province x month ------------------------------------------------
    order = list(latest.sort_values("share_above", ascending=False)["commodity_id"])
    commodity = st.selectbox("Commodity", order, format_func=lambda c: names.get(c, c),
                             key="a4_commodity")
    pnames = province_names()
    monthly = query("""select province_id, month, share_above, n_days, regulations
                       from ana_a4_compliance_monthly
                       where commodity_id = ? and market_tier = 'traditional'
                       order by month""", (commodity,))
    prov = query("""select province_id, share_above, longest_streak_days, current_streak_days
                    from ana_a4_compliance_province
                    where commodity_id = ? and market_tier = 'traditional'""", (commodity,))
    if monthly.empty or prov.empty:
        st.info("No months to show.")
        return
    prov_order = list(prov.sort_values("share_above", ascending=False)["province_id"])
    grid = monthly.pivot(index="province_id", columns="month", values="share_above")
    grid = grid.reindex(prov_order)
    regs_by_month = monthly.groupby("month")["regulations"].first()
    worst = prov.sort_values("longest_streak_days").iloc[-1]
    title = (f"{short.get(commodity, commodity)}: longest run above the reference "
             f"{int(worst['longest_streak_days'])} published days "
             f"({pnames[worst['province_id']]})")
    heat = go.Figure(go.Heatmap(
        z=grid.to_numpy(), x=list(grid.columns), y=[pnames[p] for p in grid.index],
        zmin=0, zmax=1,
        colorscale=[[i / (len(SEQUENTIAL_BLUE[mode]) - 1), c]
                    for i, c in enumerate(SEQUENTIAL_BLUE[mode])],
        customdata=[[regs_by_month.get(m, "") for m in grid.columns] for _ in grid.index],
        colorbar={"title": "Days above", "tickformat": ".0%"},
        xgap=1, ygap=1,
        hovertemplate=("%{y}, %{x|%b %Y}: above on %{z:.0%} of days<br>%{customdata}"
                       "<extra></extra>"),
    ))
    heat.update_layout(
        title={"text": title, "font": {"size": 15}}, height=max(440, 20 * len(grid)),
        margin={"l": 10, "r": 10, "t": 60, "b": 10},
        yaxis={"autorange": "reversed", "tickmode": "array",
               "tickvals": [pnames[p] for p in grid.index], "tickfont": {"size": 11}},
    )
    st.plotly_chart(heat, theme="streamlit", width="stretch")

    with st.expander("Regulations and table view"):
        t = regs[regs["commodity_id"] == commodity].sort_values("first_date")
        periods = [f"{pd.Timestamp(a):%d %b %Y} – {pd.Timestamp(b):%d %b %Y}"
                   for a, b in zip(t["first_date"], t["last_date"], strict=True)]
        refs = [rupiah(lo) if lo == hi else f"{rupiah(lo)} – {rupiah(hi)}"
                for lo, hi in zip(t["reference_min_idr"], t["reference_max_idr"], strict=True)]
        st.dataframe(pd.DataFrame({
            "Regulation": t["regulation"],
            "Type": t["price_type"],
            "In force (in data)": periods,
            "Reference": refs,
            "Province-days above": t["share_above"].map(lambda v: f"{v:.0%}"),
            "Median excess when above": t["median_excess_when_above"].map(
                lambda v: "–" if pd.isna(v) else f"{v:.0%}"),
            "Source": t["source_url"],
            "Source kind": t["source_kind"].str.replace("_", " "),
        }), hide_index=True, column_config={"Source": st.column_config.LinkColumn()})
        st.caption("Reference prices differ by zone; the range shows the lowest and highest "
                   "zone. 'Press report' rows were checked against news because no official "
                   "copy was found online.")
    st.markdown(
        "**How it's measured.** Each province's traditional-market price is compared every "
        "published day with the HET or HAP in force for its zone on that day. A run counts "
        "published days in a row above the reference and continues across a regulation change "
        "while the price stays above the new one."
    )


def transmission_tab() -> None:
    if not (table_exists("ana_a2_transmission_summary")
            and table_exists("ana_a2_transmission_lags")):
        st.info("This analysis appears after the next weekly update.")
        return
    summ = query("""select commodity_id, n_provinces, rise_same_month, fall_same_month,
                           rise_total, fall_total, p_value_equal_totals,
                           p_value_equal_same_month, r_squared, first_month, last_month
                    from ana_a2_transmission_summary""")
    if summ.empty:
        st.info("Not enough matched producer and market prices yet.")
        return
    st.markdown(
        "**Question:** when the producer price moves, how much of it reaches the market "
        "price, and how fast? Do rises travel faster than falls?"
    )
    up_color, down_color = DIVERGING[mode][-1], DIVERGING[mode][0]
    s = summ.sort_values("rise_same_month")
    ylab = [short.get(c, c) for c in s["commodity_id"]]
    fig = go.Figure()
    for col, label, color in [("rise_same_month", "10% rise", up_color),
                              ("fall_same_month", "10% fall", down_color)]:
        fig.add_trace(go.Bar(
            x=s[col] * 10, y=ylab, orientation="h", name=label, marker={"color": color},
            hovertemplate=("%{y}: a " + label + " in the producer price moves the market "
                           "price %{x:.1f}% the same month<extra></extra>"),
        ))
    rice = summ[summ["commodity_id"] == "beras_medium_1"]
    faster = int(((summ["rise_same_month"] > summ["fall_same_month"])
                  & (summ["p_value_equal_same_month"] < 0.05)).sum())
    if not rice.empty:
        r = rice.iloc[0]
        title = (f"Rises reach the market faster than falls for {faster} of {len(summ)} foods: "
                 f"medium rice moves {r['rise_same_month'] * 10:.1f}% the same month after a "
                 f"10% producer rise, {abs(r['fall_same_month']) * 10:.1f}% after a 10% fall")
    else:
        title = f"Rises reach the market faster than falls for {faster} of {len(summ)} foods"
    fig.update_layout(
        barmode="group", title={"text": title, "font": {"size": 15}},
        height=max(440, 30 * len(s)), margin={"l": 10, "r": 10, "t": 60, "b": 10},
        xaxis={"title": "Market price change in the same month, % (per 10% producer change)"},
        legend={"orientation": "h", "y": -0.1}, bargap=0.25,
    )
    st.plotly_chart(fig, theme="streamlit", width="stretch")
    st.caption(f"Months {pd.Timestamp(summ['first_month'].min()):%b %Y} to "
               f"{pd.Timestamp(summ['last_month'].max()):%b %Y}, pooled over provinces with "
               "both producer and traditional-market prices.")

    order = list(summ.sort_values("rise_same_month", ascending=False)["commodity_id"])
    commodity = st.selectbox("Commodity", order, format_func=lambda c: names.get(c, c),
                             index=order.index("beras_medium_1")
                             if "beras_medium_1" in order else 0, key="a2_commodity")
    lags = query("""select direction, lag_months, cumulative from ana_a2_transmission_lags
                    where commodity_id = ? order by direction, lag_months""", (commodity,))
    row = summ[summ["commodity_id"] == commodity].iloc[0]
    title = (f"{short.get(commodity, commodity)}: a 10% producer rise lifts the market price "
             f"{row['rise_total'] * 10:.1f}% within two months, a 10% fall lowers it "
             f"{abs(row['fall_total']) * 10:.1f}%")
    line = go.Figure()
    for direction, label, color in [("rise", "10% rise", up_color),
                                    ("fall", "10% fall", down_color)]:
        d = lags[lags["direction"] == direction]
        line.add_trace(go.Scatter(
            x=d["lag_months"], y=d["cumulative"].abs() * 10, name=label,
            mode="lines+markers", line={"color": color, "width": 2}, marker={"size": 8},
            hovertemplate=("After %{x} months: " + label + " → %{y:.1f}% in the market price"
                           "<extra></extra>"),
        ))
    line.update_layout(
        title={"text": title, "font": {"size": 15}}, height=360,
        margin={"l": 10, "r": 10, "t": 60, "b": 10},
        xaxis={"title": "Months after the producer change", "tickvals": [0, 1, 2],
               "ticktext": ["Same month", "1 month", "2 months"]},
        yaxis={"title": "Market price change, % (size)", "rangemode": "tozero"},
        legend={"orientation": "h", "y": -0.2},
    )
    st.plotly_chart(line, theme="streamlit", width="stretch")

    with st.expander("Table view"):
        t = summ.sort_values("rise_same_month", ascending=False)
        st.dataframe(pd.DataFrame({
            "Commodity": [names.get(c, c) for c in t["commodity_id"]],
            "Rise, same month": (t["rise_same_month"] * 10).map(lambda v: f"{v:.1f}%"),
            "Fall, same month": (t["fall_same_month"].abs() * 10).map(lambda v: f"{v:.1f}%"),
            "Rise, 2 months": (t["rise_total"] * 10).map(lambda v: f"{v:.1f}%"),
            "Fall, 2 months": (t["fall_total"].abs() * 10).map(lambda v: f"{v:.1f}%"),
            "Same-month gap p": t["p_value_equal_same_month"].map(lambda v: f"{v:.3f}"),
            "2-month gap p": t["p_value_equal_totals"].map(lambda v: f"{v:.3f}"),
            "Provinces": t["n_provinces"],
        }), hide_index=True)
        st.caption("Per 10% producer change. p below 0.05 = the rise/fall gap is unlikely to "
                   "be chance; with 19 foods tested, about one would pass by chance.")
    st.markdown(
        "**How it's measured.** PIHPS updates producer prices once a month, so this works "
        "in months: the change in a province's average market price is regressed on rises "
        "and falls in its producer price that month and the two before, pooled over "
        "provinces. It measures how prices move together, not what causes them to."
    )


tabs = st.tabs(["Lebaran & Ramadan", "Volatility & risk", "Farm-to-market margins",
               "Producer to market speed", "Price ceilings"])
with tabs[0]:
    lebaran_tab()
with tabs[1]:
    volatility_tab()
with tabs[2]:
    margins_tab()
with tabs[3]:
    transmission_tab()
with tabs[4]:
    compliance_tab()
st.caption("One more analysis (how price moves spread between provinces) is added here "
           "when it is finished.")
footer()
