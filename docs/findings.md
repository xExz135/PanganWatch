# Findings

**Status: all six findings signed off by the project owner on 2026-10-26 (Gate 2).**

One paragraph per analysis, each with a number, a period and a place. Numbers come from the
`ana_*` tables built by dbt (`dbt/models/analyses/`); the dashboard's Insights page shows the
charts. Prices are national traditional-market prices (median across 34 provinces) from
PIHPS, Bank Indonesia, on days when at least 80% of the usual provinces reported
(`ana_national_price`).

## A5 — Lebaran and Ramadan effects

**Chilies get expensive when Ramadan starts, not in the week before Lebaran; shallots are the
opposite.** Across the five Lebarans from 2022 to 2026, red bird's-eye chili was a median 34%
above its 12-month trend in the first week of Ramadan, but only 2% above it in the last week
before Lebaran; it was dearer in Ramadan's first week than in the last week before Lebaran in 4 of
the 5 years. Red curly chili follows the same timing (+6%, then −10%). Shallots kept climbing
instead: +3% in the last week before Lebaran and +17% two to four weeks after, above trend in
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

## A6 — Volatility and risk ranking

**Sudden price jumps are a chili-and-shallot problem; most staples never jumped nationally.**
From January 2022 to October 2026, the national price of the four chilies rose 15% or more
within the next two weeks on 13–23% of days (red bird's-eye chili 23%), and shallots on 6.5%.
Cooking oil did so only in March 2022, when the packaged-oil price ceiling was lifted. The other
13 of 21 foods, including rice, sugar, beef, chicken, eggs and garlic, never rose 15% within two
weeks nationally. Locally the risk is higher: in the median province, red bird's-eye chili
jumped on 32% of days, from 14% in Nusa Tenggara Timur to 46% in Sulawesi Utara (25 provinces
with at least two reporting cities). For a buyer: chilies and shallots are where buying ahead
or a price alert pays off; staples can be bought as needed.

*Caveats.* A province price is the median of a few cities (two or three in most provinces), so
local jumps include single-market noise; the seven provinces with one reporting city are left
out. "Jump" is any 15% rise within 14 days, so a long rise counts on several days.

*Method.* `ana_a6_volatility`: share of days followed by a 15%+ rise within 14 days (the spike
label used by the forecasting team), and the standard deviation of daily log price changes,
national (`ana_national_price`) and per province. Risk: high ≥ 10% of days, medium ≥ 1%, low
below.

## A1 — Farm-to-table margins

**The fresher and more perishable the food, the smaller the producer's share.** Of every
Rp 100 paid at a traditional market from January 2022 to October 2026, the producer price was
Rp 63–70 for the four chilies and shallots, Rp 72 for chicken, and Rp 86–92 for medium rice,
eggs and beef (national median month, matched province-days only). Most of the chili gap is
added in the last step: from wholesale to market takes 16–20% of the market price for chilies,
against 5–7% for rice. The rice gap has narrowed: producers' share of the medium-rice market
price rose from 82% in the first 12 months (2022) to 87% in the last 12 months, and every
rice grade moved the same way. For a policy reader: margin pressure is in fresh produce, where
most of a price spike happens after the producer.

*Caveats.* "Producer" is PIHPS's producer tier (for rice, milled rice at the producer level,
not unhusked grain), reported by fewer provinces than retail: garlic (2 provinces), premium
sugar (6) and branded oil type 2 (8) are left out. Producer and wholesale prices often cross on
single days and in single provinces, so only monthly national medians are used. The margin
covers transport, losses and spoilage as well as profit; this analysis can't split them.

*Method.* `ana_a1_margins_monthly`: per month, the median of same-day, same-province ratios
(producer / retail, wholesale / retail) over province-days with all three prices;
`ana_a1_margins_summary`: the median month, and the first vs last 12 months.

## A4 — Reference-price compliance

**The medium-rice price ceiling has not held anywhere since 2022.** In traditional markets,
medium rice was above its HET ceiling on 97–100% of province-days under each of the five
regulations in force from January 2022 to October 2026, and 33 of 34 provinces were above it on
at least 95% of their days. East Java and Central Java, both rice-surplus provinces, were above
it on every published day since January 2022, a run still going. Under the current ceiling
(Kepbadan 299/2025, from 22 August 2025) the share is 99.9% of province-days, by a median 14%.
Reference prices (HAP) for other foods hold more often: since the June 2024 increases, eggs
were above theirs on 46% of province-days (81–82% under the two earlier references) and
chicken on 37% (61% in 2022). Red bird's-eye chili was above its HAP on 60% of province-days
since September 2024, by a median 39% when above. For a policy reader: the rice ceiling
describes a price few traditional markets charge.

*Caveats.* PIHPS's "medium rice I" may not match the regulation's definition of medium rice
exactly, so part of the gap can be grade. HAP is a reference price, not a legal ceiling, and
its upper bound is used. Four regulations were checked against news reports because no
official copy was found online (`source_kind = press_report`): the rice ceilings of 2017 and
2025, the 2024 relaxation letters, and the 2020 egg and chicken references.

*Method.* `fct_reference_compliance` compares each province's daily price with the HET/HAP in
force for its zone. `ana_a4_compliance_regulation` (per regulation, with its source),
`ana_a4_compliance_province` (days above, longest and current run of published days above) and
`ana_a4_compliance_monthly` (the heatmap).

## A2 — Asymmetric price transmission

**Producer price rises reach the market faster than falls, then the two even out.** Pooling
provinces from April 2022 to September 2026, a 10% rise in the producer price of medium rice
lifted its traditional-market price by 2.2% in the same month, but a 10% fall lowered it by only
0.7%; after two months the two were similar (3.2% and 2.8%). Rises travelled faster in the same
month for all six rice grades and all four chilies (each difference significant at 5%), and for
grade-1 beef, where falls also never caught up (2.6% versus 1.0% after two months). Chilies pass
on the most: a 10% producer rise in red bird's-eye chili moved the market price 6.1% the same
month. Over two months, total pass-through differed for only 5 of 19 foods, and for shallots and
chicken it was falls that passed through more fully. For a policy reader: when producer prices
drop, shoppers see the saving a month or more later than they would see a rise.

*Caveats.* PIHPS updates producer prices only once a month, so this is measured in months, not
the spec's weeks (owner_requests DA #5), and anything faster than a month is invisible. Producer
and market prices come from partly different cities. With 19 foods tested, about one would show
a difference by chance; the rice and chili pattern holds in every grade. This measures how
prices move together, not what causes them to.

*Method.* `python -m analytics.run` (weekly): per commodity, the monthly change in a province's
average market price is regressed on rises and falls in its producer price (the figure at month
end) in the same month and the two before, pooled over provinces with errors clustered by
province; Wald tests compare rises and falls in the same month and in total
(`ana_a2_transmission_summary`, `ana_a2_transmission_lags`).

## A3 — Spatial spillover

**A price move in Java's producing provinces shows up the same day in nearby provinces and
fades with distance; it doesn't travel outward over days.** From January 2022 to October 2026,
daily traditional-market price changes of red bird's-eye chili in provinces within 500 km of a
producing centre moved with the centres' change on the same day (median correlation 0.57),
against 0.08 for provinces more than 1,500 km away; across provinces, the link weakened with
distance (correlation −0.65). Curly chili (0.34 near, 0.02 far), chicken (0.25, 0.01) and
eggs (0.19, 0.03) follow the same pattern. Of the 84 province links clear enough to time
(correlation ≥ 0.2), 49 peak on the same day and 74 within a week. Rice is the exception:
daily changes hardly line up anywhere (median same-day correlation 0.01). For a regional
buyer: a Java chili jump is a same-day signal for Banten, Lampung or Bali, but says little
about prices in Papua or Maluku.

*Caveats.* The producing centres are a hand-made list (`production_centers` seed, marked
unverified). A correlation shows prices moving together, not one causing the other: a shared
shock such as weather or a holiday can move everywhere at once. Lags of 7 or more days may
reflect PIHPS's weekly rhythm rather than travel time. Provinces with one reporting city are
left out.

*Method.* `ana_a3_spillover_lags`: correlation between each non-centre province's daily log
price change and the centres' change (median of the centre provinces, on days they all
reported) 0–21 days earlier; `ana_a3_spillover`: same-day correlation, the best lag where the
link is clear, and the distance to the nearest centre.
