{{ config(materialized='table') }}
-- National traditional-market price per commodity and day = median across provinces, kept
-- only on days when at least 80% of the provinces that usually report it did. On holidays a
-- few provinces report alone (1-2 around Lebaran 2022), and their median is not a national
-- price. Shared by the A5 and A6 analyses.

with daily as (
    select date, commodity_id, median(price_idr) as price_idr, count(*) as n_provinces
    from {{ ref('fct_daily_price') }}
    where market_tier = 'traditional' and not is_imputed
    group by all
),

usual as (
    select commodity_id, median(n_provinces) as usual_provinces
    from daily
    group by all
)

select
    d.date,
    d.commodity_id,
    d.price_idr,
    d.n_provinces,
    u.usual_provinces
from daily as d
inner join usual as u using (commodity_id)
where d.n_provinces >= 0.8 * u.usual_provinces
