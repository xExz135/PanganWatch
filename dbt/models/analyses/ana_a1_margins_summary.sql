{{ config(materialized='table') }}
-- A1 summary per commodity: median monthly shares over the whole history, their range, and the
-- first vs the last 12 months. Of each Rp 100 paid at a traditional market:
--   producer_share                  -> the producer price
--   wholesale_share - producer_share -> producer-to-wholesale margin
--   1 - wholesale_share             -> wholesale-to-retail margin
-- (medians of ratios, so the three parts add up to about, not exactly, 100).
-- is_thin: producer prices from fewer than 10 provinces in a typical month.

with m as (select * from {{ ref('ana_a1_margins_monthly') }}),

bounds as (select min(month) as first_month, max(month) as last_month from m)

select
    m.commodity_id,
    count(*) as n_months,
    median(m.n_provinces) as median_provinces,
    median(m.n_provinces) < 10 as is_thin,
    median(m.producer_share) as producer_share,
    min(m.producer_share) as producer_share_min,
    max(m.producer_share) as producer_share_max,
    median(m.wholesale_share) as wholesale_share,
    median(m.producer_share) filter (where m.month < b.first_month + interval 12 month)
        as producer_share_first_12m,
    median(m.producer_share) filter (where m.month > b.last_month - interval 12 month)
        as producer_share_last_12m
from m
cross join bounds as b
group by all
