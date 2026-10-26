"""Insights: what do five years of prices say? One tab per analysis (spec Phase 2).

A5 Lebaran & Ramadan effects reads ana_a5_lebaran_phases / ana_a5_lebaran_curve
(dbt/models/analyses/). Other analyses get a tab when their tables exist.
"""

import plotly.graph_objects as go
import streamlit as st
from common import (
    DIVERGING,
    TIER_COLORS,
    V1_COMMODITIES,
    commodity_names,
    footer,
    page_header,
    query,
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


tabs = st.tabs(["Lebaran & Ramadan"])
with tabs[0]:
    lebaran_tab()
st.caption("More analyses (farm-to-market margins, volatility, price-ceiling breaches, how "
           "price moves spread between provinces) are added here as they are finished.")
footer()
