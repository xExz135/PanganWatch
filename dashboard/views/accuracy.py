"""Page 5 — Forecast accuracy: how close were past forecasts to the real price? (spec §12)

Live record: every published forecast graded against the price PIHPS later published
(fct_forecast_ledger joined to fct_forecast), for the live model and any shadow model.
Backtest: 13 months of past data (fct_model_metrics), baselines next to the models, normal
days vs Ramadan-Lebaran. Same measures on both sides so they can be read side by side:
  typical error  = sMAPE of the likely price (q50), as a share of the price
  vs baseline    = geometric mean over series of MAE(model) / MAE(baseline), same forecasts
  range caught   = share of actual prices inside the 80% range (q10..q90); 80% is the aim
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from common import (
    DIVERGING,
    V1_COMMODITIES,
    commodity_names,
    footer,
    live_model,
    page_header,
    province_names,
    query,
    rgba,
    short_names,
    table_exists,
    theme,
)

HORIZONS = {7: "1 week", 14: "2 weeks", 28: "4 weeks", 1: "1 day"}
WINDOWS = {"Last 30 days": 30, "Last 90 days": 90, "All": None}
MIN_GRADED = 200  # below this per model, numbers are shown as early and unsettled
DEFAULT_PROVINCE = 31
BASELINE = "naive"
LABEL = {
    "naive": "Baseline: no change",
    "seasonal_naive": "Baseline: same day last week",
    "lgbm_quantile": "LightGBM, all foods",
    "lgbm_routed": "LightGBM where it helped",
}
# fixed slot per model (reference categorical order), so a filter never repaints a line
COLORS = {
    "light": {"naive": "#2a78d6", "lgbm_routed": "#eb6834", "seasonal_naive": "#1baf7a",
              "lgbm_quantile": "#eda100"},
    "dark": {"naive": "#3987e5", "lgbm_routed": "#d95926", "seasonal_naive": "#199e70",
             "lgbm_quantile": "#c98500"},
}
ORDER = ["naive", "seasonal_naive", "lgbm_quantile", "lgbm_routed"]

page_header("Forecast accuracy", "How close were past forecasts to the real price?")
mode = theme()
names = commodity_names()
short = short_names()
live = live_model()


def label(model: str) -> str:
    base = LABEL.get(model, model)
    return f"{base} (live)" if model == live else base


def smape(actual: pd.Series, pred: pd.Series) -> float:
    a, p = actual.astype(float), pred.astype(float)
    return float((2 * (a - p).abs() / (a.abs() + p.abs())).mean())


def rel_to_baseline(df: pd.DataFrame, model: str) -> float:
    """Geometric mean over series of MAE(model) / MAE(baseline) on the same forecasts."""
    k = ["run_date", "commodity_id", "province_id", "horizon_days"]
    pair = (df[df["model_name"].isin([model, BASELINE])]
            .pivot_table(index=k, columns="model_name", values="abs_error").dropna())
    if pair.empty or model not in pair or BASELINE not in pair:
        return np.nan
    s = pair.groupby(level=["commodity_id", "province_id"]).mean()
    s = s[(s[BASELINE] > 0) & (s[model] > 0)]
    return float(np.exp(np.log(s[model] / s[BASELINE]).mean())) if len(s) else np.nan


def vs(ratio: float) -> str:
    if pd.isna(ratio):
        return "–"
    return f"{abs(ratio - 1):.1%} {'lower' if ratio < 1 else 'higher'}"


# --- one filter row scoping everything below --------------------------------------------
f1, f2 = st.columns(2)
horizon = f1.selectbox("Forecast length", list(HORIZONS), format_func=HORIZONS.get)
window = f2.selectbox("Live record period", list(WINDOWS), index=1)

# --- live record ------------------------------------------------------------------------
st.subheader("Live record")
st.caption("Every forecast published since the daily job started, checked against the price "
           "PIHPS published on its target date. Forecasts can't be changed after they are "
           "made; a dbt test checks this every day.")

ready = table_exists("fct_forecast_ledger") and table_exists("fct_forecast")
graded = pd.DataFrame()
if ready:
    days = WINDOWS[window]
    graded = query(f"""
        with l as (
            select * from fct_forecast_ledger where horizon_days = ?
            {"and target_date > (select max(target_date) from fct_forecast_ledger) - ?"
             if days else ""}
        )
        select l.run_date, l.target_date, l.horizon_days, l.commodity_id, l.province_id,
               split_part(l.model_version, '-', 1) as model_name, l.actual_price,
               l.abs_error, l.in_interval_80, f.q10, f.q50, f.q90
        from l join fct_forecast as f
            using (run_date, model_version, commodity_id, province_id, horizon_days)
    """, (horizon, days) if days else (horizon,))

if graded.empty:
    first = query("select min(run_date) as d from fct_forecast") if ready or table_exists(
        "fct_forecast") else pd.DataFrame()
    when = ""
    if not first.empty and pd.notna(first["d"].iloc[0]):
        due = pd.Timestamp(first["d"].iloc[0]) + pd.Timedelta(days=horizon + 1)
        when = f" The first {HORIZONS[horizon]} forecasts are graded around {due:%d %b %Y}."
    st.info(f"No {HORIZONS[horizon]} forecasts graded yet: each one is checked the day after "
            f"its target date.{when}")
else:
    models = [m for m in ORDER if m in set(graded["model_name"])] + sorted(
        set(graded["model_name"]) - set(ORDER))
    cols = st.columns(len(models))
    for col, m in zip(cols, models, strict=True):
        g = graded[graded["model_name"] == m]
        with col:
            st.markdown(f"**{label(m)}**")
            st.metric("Typical error", f"{smape(g['actual_price'], g['q50']):.1%}",
                      help="Average gap between the likely price and the real price, as a "
                           "share of the price (sMAPE).")
            st.metric("Range caught the real price", f"{g['in_interval_80'].mean():.0%}",
                      help="Share of real prices inside the 80% range. Close to 80% means "
                           "the ranges are honest.")
            if m != BASELINE:
                st.metric("Error vs baseline", vs(rel_to_baseline(graded, m)),
                          help="On exactly the same forecasts, per province and food.")
            st.caption(f"{len(g):,} forecasts graded"
                       + (" · early days, numbers will move" if len(g) < MIN_GRADED else ""))

    # error over time, one line per model
    weekly = (graded.assign(week=graded["target_date"].dt.to_period("W").dt.start_time)
              .groupby(["model_name", "week"])
              .apply(lambda g: smape(g["actual_price"], g["q50"]), include_groups=False)
              .rename("smape").reset_index())
    if weekly["week"].nunique() >= 2:
        fig = go.Figure()
        for m in models:
            w = weekly[weekly["model_name"] == m]
            c = COLORS[mode].get(m, "#898781")
            fig.add_trace(go.Scatter(
                x=w["week"], y=w["smape"], mode="lines+markers", name=label(m),
                line={"color": c, "width": 2}, marker={"size": 8, "color": c},
                hovertemplate="Week of %{x|%d %b}: typical error %{y:.1%}<extra>"
                              + label(m) + "</extra>",
            ))
        fig.update_layout(
            title={"text": f"Typical error of {HORIZONS[horizon]} forecasts, by week of the "
                           "target date", "font": {"size": 15}},
            height=340, margin={"l": 10, "r": 20, "t": 60, "b": 10},
            legend={"orientation": "h", "y": -0.18},
            yaxis={"title": "Typical error", "tickformat": ".1%", "rangemode": "tozero"},
            xaxis={"title": None},
        )
        st.plotly_chart(fig, theme="streamlit", width="stretch")

    # --- forecast vs real price for one series -------------------------------------------
    st.markdown("**Forecast vs real price**")
    provs = province_names()
    s1, s2, s3 = st.columns(3)
    have = set(graded["commodity_id"])
    commodity = s1.selectbox(
        "Commodity", [c for c in V1_COMMODITIES if c in have]
        + sorted(c for c in have if c not in V1_COMMODITIES), format_func=names.get)
    plist = sorted(set(graded.loc[graded["commodity_id"] == commodity, "province_id"]),
                   key=lambda p: provs.get(p, str(p)))
    province = s2.selectbox(
        "Province", plist, format_func=lambda p: provs.get(p, str(p)),
        index=plist.index(DEFAULT_PROVINCE) if DEFAULT_PROVINCE in plist else 0)
    model = s3.selectbox("Model", models, format_func=label)
    one = graded[(graded["commodity_id"] == commodity) & (graded["province_id"] == province)
                 & (graded["model_name"] == model)].sort_values("target_date")
    c = COLORS[mode].get(model, "#898781")
    off = smape(one["actual_price"], one["q50"])
    title = (f"{short.get(commodity, commodity)} in {provs.get(province, province)}: "
             f"{HORIZONS[horizon]} forecasts were off by {off:.1%} on average; the range "
             f"caught the real price {one['in_interval_80'].mean():.0%} of the time")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=one["target_date"], y=one["q50"], mode="markers", name="Likely price (forecast)",
        marker={"size": 8, "color": c},
        error_y={"type": "data", "symmetric": False, "array": one["q90"] - one["q50"],
                 "arrayminus": one["q50"] - one["q10"], "color": rgba(c, 0.5),
                 "thickness": 2, "width": 0},
        customdata=one[["run_date", "q10", "q90"]],
        hovertemplate="For %{x|%a %d %b}, made %{customdata[0]|%d %b}<br>Likely Rp %{y:,.0f}"
                      "<br>80% range Rp %{customdata[1]:,.0f} to Rp %{customdata[2]:,.0f}"
                      "<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=one["target_date"], y=one["actual_price"], mode="lines", name="Real price",
        line={"color": "#898781", "width": 2},
        hovertemplate="%{x|%a %d %b}: real price Rp %{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title={"text": title, "font": {"size": 15}}, height=380,
        margin={"l": 10, "r": 20, "t": 60, "b": 10}, legend={"orientation": "h", "y": -0.18},
        yaxis={"title": "Rupiah", "tickformat": ",.0f"}, xaxis={"title": "Target date"},
    )
    st.plotly_chart(fig, theme="streamlit", width="stretch")
    st.caption("Dots: the likely price, with a bar for the 80% range. Gray line: the price "
               "actually published that day.")

# --- backtest ---------------------------------------------------------------------------
st.subheader("Backtest: 13 months of past data")
bt = (query("""
    select * from fct_model_metrics
    where task = 'forecast' and horizon_days = ?
    qualify model_version = arg_max(model_version, evaluated_at)
        over (partition by model_name)
""", (horizon,)) if table_exists("fct_model_metrics") else pd.DataFrame())
if bt.empty:
    st.info("Backtest results appear after the next data update.")
else:
    st.caption("Each model was retrained every 4 weeks on the prices before that point and then "
               "forecast the next 4 weeks, so it never saw the prices it was scored on. The "
               "machine-learning model goes live only if it beats the baseline here and on the "
               "live record.")
    total = bt[bt["commodity_id"].isna()]

    def get(m: str, metric: str, segment: str = "all") -> float:
        v = total[(total["model_name"] == m) & (total["metric"] == metric)
                  & (total["segment"] == segment)]["value"]
        return float(v.iloc[0]) if len(v) else np.nan

    live_err = ({m: smape(g["actual_price"], g["q50"])
                 for m, g in graded.groupby("model_name")} if not graded.empty else {})
    rows = []
    for m in [m for m in ORDER if m in set(total["model_name"])]:
        share = get(m, "share_series_beating_naive")
        rows.append({
            "Model": label(m),
            "Typical error": f"{get(m, 'smape'):.1%}",
            "Normal days": f"{get(m, 'smape', 'normal'):.1%}",
            "Ramadan–Lebaran": f"{get(m, 'smape', 'ramadan_lebaran'):.1%}",
            "Error vs baseline": "–" if m == BASELINE else vs(get(m, "relmae_naive")),
            "Beat the baseline in": "–" if pd.isna(share) else f"{share:.0%} of series",
            "Range caught the real price": f"{get(m, 'coverage_80'):.0%}",
            "Live typical error": f"{live_err[m]:.1%}" if m in live_err else "not yet",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    # per food: where does the model help?
    model_choices = [m for m in ("lgbm_routed", "lgbm_quantile") if m in set(bt["model_name"])]
    if model_choices:
        pick = model_choices[0]
        per = bt[(bt["model_name"] == pick) & (bt["segment"] == "all")
                 & (bt["metric"] == "relmae_naive") & bt["commodity_id"].notna()]
        per = per.assign(change=per["value"] - 1).sort_values("change", ascending=False)
        better = per[per["change"] <= -0.0005]
        best = per.iloc[-1] if len(per) else None
        title = (f"{LABEL[pick]}: lower error than the baseline on {len(better)} of {len(per)} "
                 f"foods at {HORIZONS[horizon]}"
                 + (f"; best: {short.get(best['commodity_id'], best['commodity_id'])}, "
                    f"{best['change']:+.0%}" if best is not None and best["change"] < 0
                    else ""))
        lo_c, mid_c, hi_c = DIVERGING[mode][0], DIVERGING[mode][2], DIVERGING[mode][-1]
        same = per["change"].abs() < 0.0005  # always used the baseline: identical forecasts
        bars = go.Figure(go.Bar(
            x=per["change"], y=[short.get(c, c) for c in per["commodity_id"]], orientation="h",
            marker={"color": [mid_c if z else lo_c if v < 0 else hi_c
                              for v, z in zip(per["change"], same, strict=True)]},
            text=["same" if z else f"{v:+.1%}"
                  for v, z in zip(per["change"], same, strict=True)],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{x:+.1%} error vs the baseline<extra></extra>",
        ))
        bars.update_layout(
            title={"text": title, "font": {"size": 15}}, height=max(380, 24 * len(per)),
            margin={"l": 10, "r": 50, "t": 60, "b": 10}, bargap=0.3,
            xaxis={"title": "Error compared with the baseline (negative = more accurate)",
                   "tickformat": "+.0%", "zeroline": True},
        )
        st.plotly_chart(bars, theme="streamlit", width="stretch")
        st.caption("Blue: more accurate than the baseline. Red: less accurate. \"Same\": the "
                   "model kept the baseline for that food. Stable prices (rice, cooking oil, "
                   "sugar) barely move, so \"no change\" is hard to beat.")

footer()
