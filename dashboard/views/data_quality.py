"""Page 7 — Data quality & about: is the data healthy? (spec §8, §12)"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from common import (
    GITHUB_URL,
    SEQUENTIAL_BLUE,
    STATUS,
    V1_COMMODITIES,
    footer,
    latest_price_date,
    page_header,
    province_names,
    query,
    table_exists,
    theme,
)

page_header("Data quality & about", "Is the data healthy?")
latest = latest_price_date()
mode = theme()

# --- pipeline runs ----------------------------------------------------------------------
st.subheader("Pipeline runs")
runs = (query("select * from fct_pipeline_runs order by started_at desc")
        if table_exists("fct_pipeline_runs") else pd.DataFrame())
if runs.empty:
    st.info("No automatic runs logged yet. The daily job starts once the history "
            "upload is done; until then this page shows the data quality of the loaded history.")
else:
    ok = runs[runs["status"] == "success"]
    last = runs.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Last run", f"{'✅ Passed' if last['status'] == 'success' else '❌ Failed'}",
              help=f"Started {last['started_at']:%d %b %Y %H:%M} UTC")
    c2.metric("Last successful run",
              ok["started_at"].iloc[0].strftime("%d %b %H:%M UTC") if not ok.empty else "–")
    window = runs.head(30)
    c3.metric("Successful runs (last 30)", f"{(window['status'] == 'success').mean():.0%}",
              help="Target ≥ 95% (spec §2)")
    c4.metric("Rows loaded in last run", f"{int(last['rows_loaded']):,}")
    with st.expander("Run history (table)"):
        st.dataframe(runs[["started_at", "status", "rows_loaded", "requests_failed",
                           "tests_failed", "tests_warned", "notes"]],
                     hide_index=True, width="stretch")

# --- missing-days heatmap ---------------------------------------------------------------
st.subheader("Coverage")
if latest is not None:
    ids = tuple(V1_COMMODITIES)
    marks = ", ".join("?" * len(ids))
    cov = query(f"""
        select date, province_id, count(distinct commodity_id) as n
        from fct_daily_price
        where market_tier = 'traditional' and commodity_id in ({marks})
          and date > ?::date - 90
        group by all
    """, (*ids, latest))
    provs = province_names()
    days = sorted(cov["date"].unique())
    grid = (cov.assign(share=cov["n"] / len(ids))
            .pivot(index="province_id", columns="date", values="share")
            .reindex(index=list(provs), columns=days).fillna(0))
    full_days = (grid >= 1).sum(axis=1)
    complete = int((full_days == len(days)).sum()) if days else 0
    heat = go.Figure(go.Heatmap(
        z=grid.values, x=[pd.Timestamp(d) for d in days], y=[provs[p] for p in grid.index],
        zmin=0, zmax=1, xgap=1, ygap=1,
        colorscale=[[i / (len(SEQUENTIAL_BLUE[mode]) - 1), c]
                    for i, c in enumerate(SEQUENTIAL_BLUE[mode])],
        colorbar={"title": "Share of 8<br>commodities", "tickformat": ".0%"},
        hovertemplate="%{y}<br>%{x|%d %b %Y}: %{z:.0%} reported<extra></extra>",
    ))
    heat.update_layout(
        title={"text": f"{complete} of {len(provs)} provinces reported all 8 commodities on "
                       f"every published day of the last 90 days", "font": {"size": 15}},
        height=max(420, 22 * len(provs)), margin={"l": 10, "r": 10, "t": 50, "b": 10},
        # every province labelled: auto tick-skipping put labels on the wrong rows
        yaxis={"autorange": "reversed", "tickfont": {"size": 11}, "tickmode": "array",
               "tickvals": [provs[p] for p in grid.index],
               "ticktext": [provs[p] for p in grid.index]},
    )
    st.plotly_chart(heat, theme="streamlit", width="stretch")
    st.caption("Traditional-market tier. Weekends and holidays are not shown: PIHPS "
               "publishes on working days only. Palest = nothing reported that day.")

# --- test results -----------------------------------------------------------------------
st.subheader("Quality checks")
tests = (query("""
    select r.started_at, t.status, count(*) as n
    from fct_test_results as t join fct_pipeline_runs as r using (run_id)
    group by all order by r.started_at
""") if table_exists("fct_test_results") else pd.DataFrame())
if tests.empty:
    st.info("Check results appear here after the first logged run. Each run executes "
            "about 50 checks: duplicates, units, price bounds, daily jumps, freshness, "
            "coverage and the producer ≤ wholesale ≤ retail order.")
else:
    labels = {"pass": "✅ Pass", "warn": "⚠️ Warn", "fail": "❌ Fail"}
    colors = {"pass": STATUS["good"], "warn": STATUS["warning"], "fail": STATUS["critical"]}
    bars = go.Figure()
    for status in ["pass", "warn", "fail"]:
        s = tests[tests["status"] == status]
        bars.add_trace(go.Bar(x=s["started_at"], y=s["n"], name=labels[status],
                              marker={"color": colors[status], "line": {"width": 0}}))
    last_run = tests[tests["started_at"] == tests["started_at"].max()]
    n_fail = int(last_run.loc[last_run["status"] == "fail", "n"].sum())
    n_warn = int(last_run.loc[last_run["status"] == "warn", "n"].sum())
    bars.update_layout(
        barmode="stack", bargap=0.3, height=320,
        title={"text": f"Last run: {n_fail} failed, {n_warn} warnings "
                       f"(warnings flag rows but don't stop the pipeline)", "font": {"size": 15}},
        margin={"l": 10, "r": 10, "t": 50, "b": 10}, legend={"orientation": "h", "y": -0.2},
        yaxis={"title": "Checks"},
    )
    st.plotly_chart(bars, theme="streamlit", width="stretch")
    with st.expander("Last run's warnings and failures (table)"):
        st.dataframe(query("""
            select test_name, model_name, layer, severity, status, failures
            from fct_test_results
            where run_id = (select run_id from fct_pipeline_runs order by started_at desc limit 1)
              and status <> 'pass'
            order by status, failures desc
        """), hide_index=True, width="stretch")

st.caption("**PIHPS vs Bapanas cross-check:** not yet available. Bapanas is an optional "
           "second source (spec S2); this check switches on when it is added.")

# --- about ------------------------------------------------------------------------------
st.subheader("About")
st.markdown(f"""
**How the numbers are made.** Each weekday PanganWatch collects prices from Bank Indonesia's
PIHPS for 21 commodities in four market tiers (producer, wholesale, traditional market,
modern retail) across 171 cities. A **province price** is the median of the cities that
reported that day, so one city's typo doesn't move it. Nothing is filled in: a missing day
stays missing. Every run passes about 50 automated checks before anything is published; if
one fails, the previous day's data stays live.

**Assumptions to know.**
- Prices are what PIHPS reports; cities sometimes enter typos, which the checks flag.
- Weekends and holidays have no prices; changes are measured in calendar days.
- Weather is taken at each province's capital, one point per province.

**Credits.** PIHPS Nasional — Bank Indonesia · Badan Pusat Statistik (BPS) · weather data by
Open-Meteo.com (CC BY 4.0) · USD/IDR from the European Central Bank via Frankfurter.

[Code, methodology and decisions on GitHub]({GITHUB_URL})
""")

footer()
