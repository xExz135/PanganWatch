# Findings

One paragraph per analysis, each with a number, a period and a place. Numbers come from the
`ana_*` tables built by dbt (`dbt/models/analyses/`); the dashboard's Insights page shows the
charts. Prices are national traditional-market prices (median across 34 provinces) from
PIHPS, Bank Indonesia.

## A5 — Lebaran and Ramadan effects

**Chilies get expensive when Ramadan starts, not in the week before Lebaran; shallots are the
opposite.** Across the five Lebarans from 2022 to 2026, red bird's-eye chili was a median 35%
above its 12-month trend in the first week of Ramadan, but only 2% above it in the last week
before Lebaran; it was dearer in Ramadan's first week than in the last week before Lebaran in 4 of
the 5 years. Red curly chili follows the same timing (+6%, then −10%). Shallots kept climbing
instead: +6% in the last week before Lebaran and +16% two to four weeks after, above trend in
all five years (range +7% to +53%). In the median year, medium rice and bulk cooking oil stayed within 1% of trend
throughout. For a buyer: stock chilies before Ramadan starts, and buy shallots before Lebaran
rather than after.

*Caveats.* Five events is a small sample, and the size of the chili rise varies widely (from
−8% in 2022 to +65% in 2026 in Ramadan's first week), so the timing is more reliable than the
size. 2022 is unusual: the cooking-oil crisis and the first unrestricted post-COVID homecoming
both fell on that Lebaran. The analysis shows when prices move, not why.

*Method.* National price divided by its centered 365-day rolling median, set to 100 for the
week around 60 days before Lebaran; per-year phase averages, then the median across years
(`ana_a5_lebaran_daily`, `ana_a5_lebaran_phases`, `ana_a5_lebaran_curve`).
