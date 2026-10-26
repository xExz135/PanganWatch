{{ config(materialized='table') }}
-- A1 farm-to-table margins, per commodity and month, from matched province-days only (all
-- three prices present: producer, wholesale, traditional retail). Day-level and even
-- province-month tiers cross often in PIHPS (docs/source_notes.md), so shares are medians of
-- same-day, same-province ratios across all matched province-days in the month.

select
    commodity_id,
    date_trunc('month', date)::date as month,
    count(*) as n_matched_days,
    count(distinct province_id) as n_provinces,
    median(producer_price::double / retail_price) as producer_share,
    median(wholesale_price::double / retail_price) as wholesale_share,
    median(producer_price) as producer_price_idr,
    median(wholesale_price) as wholesale_price_idr,
    median(retail_price) as retail_price_idr
from {{ ref('fct_margin_chain') }}
where producer_price is not null
  and wholesale_price is not null
  and retail_price is not null
group by all
