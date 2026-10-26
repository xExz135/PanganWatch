{{ config(materialized='table') }}
-- A4 reference-price compliance per commodity, market tier and regulation period: how often
-- the province price was above the government ceiling (HET) or reference price (HAP, upper
-- bound), and by how much. One row per regulation, with its source, so every number cites it.

with c as (select * from {{ ref('fct_reference_compliance') }}),

by_province as (
    select commodity_id, market_tier, regulation, province_id, avg(is_above::int) as share_above
    from c
    group by all
),

sources as (
    select commodity_id, regulation, any_value(source_url) as source_url,
           any_value(source_kind) as source_kind, min(price_idr) as reference_min_idr,
           max(price_idr) as reference_max_idr
    from {{ ref('dim_reference_price') }}
    group by all
)

select
    c.commodity_id,
    c.market_tier,
    c.regulation,
    any_value(c.price_type) as price_type,
    min(c.date) as first_date,
    max(c.date) as last_date,
    count(*) as n_province_days,
    count(distinct c.province_id) as n_provinces,
    avg(c.is_above::int) as share_above,
    median(c.pct_above) filter (where c.is_above) as median_excess_when_above,
    (select count(*) from by_province as b
     where b.commodity_id = c.commodity_id and b.market_tier = c.market_tier
       and b.regulation = c.regulation and b.share_above > 0.5) as n_provinces_mostly_above,
    any_value(s.reference_min_idr) as reference_min_idr,
    any_value(s.reference_max_idr) as reference_max_idr,
    any_value(s.source_kind) as source_kind,
    any_value(s.source_url) as source_url
from c
left join sources as s using (commodity_id, regulation)
group by c.commodity_id, c.market_tier, c.regulation
