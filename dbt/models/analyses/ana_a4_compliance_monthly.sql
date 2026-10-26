{{ config(materialized='table') }}
-- A4 heatmap data: share of published days above the reference, per commodity, province,
-- market tier and month, with the regulation in force (two when it changed mid-month).

select
    commodity_id,
    province_id,
    market_tier,
    date_trunc('month', date)::date as month,
    count(*) as n_days,
    avg(is_above::int) as share_above,
    median(pct_above) as median_pct_above,
    string_agg(distinct regulation, '; ') as regulations
from {{ ref('fct_reference_compliance') }}
group by all
