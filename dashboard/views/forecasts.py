"""Page 4 — Forecasts: where is this price heading in the next 4 weeks? (spec §12)

Shows the live model only (`live.model` in ml/settings.yaml); shadow models published next
to it are scored by the ledger but not shown. Price history plus the q10-q90 range from
the latest forecast run; a table of every food's range in the chosen province.
Still to come: SHAP drivers (fct_forecast_drivers) and the backtest table
(fct_model_metrics), once the Data Scientist publishes them.
"""

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from common import (
    TIER_COLORS,
    V1_COMMODITIES,
    commodity_names,
    footer,
    live_model,
    page_header,
    pct,
    per_unit,
    province_names,
    query,
    rgba,
    rupiah,
    short_names,
    table_exists,
    theme,
)

DEFAULT_PROVINCE = 31  # DKI Jakarta, the persona's province
HISTORY_DAYS = 90
MODEL_NOTE = {
    "naive": ("The current forecast is a simple baseline that assumes the price stays where "
              "it is, so the dashed line is flat. The shaded range shows how far the price "
              "could move, based on how much it moved over the same number of days in the "
              "past. A machine-learning model runs alongside it and will replace it only if "
              "it proves more accurate on real, later prices."),
}

page_header("Forecasts", "Where is this price heading in the next 4 weeks?")

model = live_model()
pattern = f"{model}-%"
runs = (query("select max(run_date) as d from fct_forecast where model_version like ?",
              (pattern,)) if table_exists("fct_forecast") else pd.DataFrame())
if runs.empty or pd.isna(runs["d"].iloc[0]):
    st.info("No forecasts published yet. They appear after the next daily update.")
    footer()
    st.stop()
run_date = pd.Timestamp(runs["d"].iloc[0]).date()

names = commodity_names()
short = short_names()
provs = province_names()
mode = theme()
color = TIER_COLORS[mode]["traditional"]  # forecasts are of the traditional-market price

# --- one filter row scoping everything below --------------------------------------------
f1, f2 = st.columns(2)
commodity = f1.selectbox(
    "Commodity", [c for c in V1_COMMODITIES if c in names]
    + sorted(c for c in names if c not in V1_COMMODITIES),
    format_func=names.get,
)
province_ids = list(provs)
province = f2.selectbox(
    "Province", province_ids, format_func=provs.get,
    index=province_ids.index(DEFAULT_PROVINCE) if DEFAULT_PROVINCE in provs else 0,
)
unit = per_unit(commodity)
place = provs[province]

fc = query("""
    select horizon_days, target_date, q10, q50, q90, model_version
    from fct_forecast
    where run_date = ? and model_version like ? and commodity_id = ? and province_id = ?
    order by horizon_days
""", (run_date, pattern, commodity, province))
hist = query("""
    select date, price_idr
    from fct_daily_price
    where commodity_id = ? and province_id = ? and market_tier = 'traditional'
      and date >= ?::date - ?
    order by date
""", (commodity, province, run_date, HISTORY_DAYS))

st.caption(f"Forecast made on {run_date:%a %d %b %Y} from prices published before that day.")

if fc.empty:
    st.info(f"No forecast for {names[commodity]} in {place}: its traditional-market price "
            "has not been published recently.")
else:
    before = hist[hist["date"] < pd.Timestamp(run_date)]
    last = before.iloc[-1] if not before.empty else None
    far = fc.iloc[-1]
    flat = last is not None and bool((fc["q50"] == last["price_idr"]).all())
    if flat:  # a no-change forecast: the range is the news, not the likely price
        title = (f"{short[commodity]} in {place}: now {rupiah(last['price_idr'])} {unit}, "
                 f"with an 80% chance of {rupiah(far['q10'])} to {rupiah(far['q90'])} "
                 f"by {far['target_date']:%d %b}")
    else:
        title = (f"{short[commodity]} in {place}: likely {rupiah(far['q50'])} {unit} on "
                 f"{far['target_date']:%d %b}, with an 80% chance of "
                 f"{rupiah(far['q10'])} to {rupiah(far['q90'])}")

    # the range fans out from the last published price
    x = ([last["date"]] if last is not None else []) + list(fc["target_date"])
    anchor = [last["price_idr"]] if last is not None else []
    hi, lo = anchor + list(fc["q90"]), anchor + list(fc["q10"])
    mid = anchor + list(fc["q50"])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=hi, mode="lines", line={"width": 0}, hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=lo, mode="lines", line={"width": 0}, fill="tonexty",
                             fillcolor=rgba(color, 0.18), name="80% range", hoverinfo="skip",
                             legendrank=3))
    fig.add_trace(go.Scatter(
        x=hist["date"], y=hist["price_idr"], mode="lines", name="Published price",
        line={"color": color, "width": 2}, legendrank=1,
        hovertemplate="%{x|%d %b %Y}: Rp %{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=x, y=mid, mode="lines+markers", name="Likely price", legendrank=2,
        line={"color": color, "width": 2, "dash": "dash"},
        # no dot on the starting point: it is the last published price, not a forecast
        marker={"size": ([0] if last is not None else []) + [8] * len(fc),
                "color": color, "line": {"width": 2, "color":
                "#1a1a19" if mode == "dark" else "#fcfcfb"}},
        customdata=([[None, None, None]] if last is not None else [])
        + [[f"in {h} day{'s' if h > 1 else ''}", rupiah(a), rupiah(b)]
           for h, a, b in zip(fc["horizon_days"], fc["q10"], fc["q90"], strict=True)],
        hovertemplate="%{x|%a %d %b}, %{customdata[0]}<br>Likely Rp %{y:,.0f}"
                      "<br>80% range %{customdata[1]} to %{customdata[2]}<extra></extra>",
    ))
    fig.add_shape(type="line", x0=run_date, x1=run_date, yref="paper", y0=0, y1=1,
                  line={"width": 1, "dash": "dot", "color": "rgba(137,135,129,0.8)"})
    fig.add_annotation(x=run_date, yref="paper", y=1, text="forecast made", showarrow=False,
                       xanchor="left", yanchor="top", font={"size": 11})
    fig.update_layout(
        title={"text": title, "font": {"size": 15}}, height=420,
        margin={"l": 10, "r": 20, "t": 60, "b": 10}, hovermode="closest",
        legend={"orientation": "h", "y": -0.12, "traceorder": "normal"},
        yaxis={"title": f"Rupiah {unit}", "tickformat": ",.0f"},
        xaxis={"title": None, "range": [pd.Timestamp(run_date) - timedelta(days=HISTORY_DAYS),
                                        far["target_date"] + timedelta(days=2)]},
    )
    st.plotly_chart(fig, theme="streamlit", width="stretch")
    st.caption(MODEL_NOTE.get(model, f"Model: {fc['model_version'].iat[0]}."))

# --- every food in this province -----------------------------------------------------------
st.subheader(f"All foods in {place}")
table = query("""
    select commodity_id, horizon_days, target_date, q10, q50, q90
    from fct_forecast
    where run_date = ? and model_version like ? and province_id = ?
      and horizon_days in (7, 28)
""", (run_date, pattern, province))
now = query("""
    select commodity_id, arg_max(price_idr, date) as price_now
    from fct_daily_price
    where province_id = ? and market_tier = 'traditional' and date < ?
      and date >= ?::date - 14
    group by commodity_id
""", (province, run_date, run_date)).set_index("commodity_id")["price_now"]
if table.empty:
    st.info(f"No forecasts for {place}.")
else:
    wide = table.pivot_table(index="commodity_id", columns="horizon_days",
                             values=["q10", "q50", "q90"], aggfunc="first")
    order = [c for c in V1_COMMODITIES if c in wide.index] + sorted(
        c for c in wide.index if c not in V1_COMMODITIES)
    # a "likely" column only when the model expects a change; else it repeats "Price now"
    moving = any(wide.loc[c, ("q50", h)] != now.get(c) for c in order for h in (7, 28)
                 if ("q50", h) in wide.columns and pd.notna(wide.loc[c, ("q50", h)]))
    rows = []
    for c in order:
        r = wide.loc[c]
        base = now.get(c)
        row = {"Food": names.get(c, c), "Unit": per_unit(c), "Price now": rupiah(base)}
        for h, label in [(7, "In 1 week"), (28, "In 4 weeks")]:
            ref = base if base is not None and pd.notna(base) else r.get(("q50", h))
            if pd.isna(r.get(("q50", h))):
                if moving:
                    row[f"{label}: likely"] = "–"
                row[f"{label}: 80% range"] = "–"
                continue
            if moving:
                row[f"{label}: likely"] = rupiah(r[("q50", h)])
            row[f"{label}: 80% range"] = (
                f"{rupiah(r[('q10', h)])} to {rupiah(r[('q90', h)])} "
                f"({pct(r[('q10', h)] / ref - 1)} / {pct(r[('q90', h)] / ref - 1)})")
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("80% range: the price should land inside it 4 times out of 5. A wide range means "
               "the price has swung a lot in the past; a narrow one means it rarely moves. "
               "Percentages are relative to the price now.")
    st.download_button(
        "Download CSV", table.assign(province=place).to_csv(index=False).encode("utf-8"),
        file_name=f"panganwatch_forecast_{run_date:%Y%m%d}_{province}.csv", mime="text/csv",
    )

footer()
