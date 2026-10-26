{{ config(materialized='table') }}
-- A3 spatial spillover: correlation between a province's daily price change and the
-- production centres' change k days earlier (k = 0..21), traditional markets.
--   centre price  = median log price of the commodity's production-centre provinces
--                   (seed production_centers), on days when all of them reported
--   daily change  = log change since the previous published day (weekends skipped)
--   lag k         = the province's change on day d vs the centres' change on day d - k
-- A correlation says how prices move together; it says nothing about cause.
{% set max_lag = 21 %}

with prices as (
    select date, commodity_id, province_id, ln(price_idr) as log_price
    from {{ ref('fct_daily_price') }}
    where market_tier = 'traditional' and not is_imputed
),

centres as (
    select commodity_id, province_id from {{ ref('production_centers') }}
),

n_centres as (
    select commodity_id, count(*) as n from centres group by all
),

centre_price as (
    select p.date, p.commodity_id, median(p.log_price) as log_price, count(*) as n_reported
    from prices as p
    inner join centres as c using (commodity_id, province_id)
    group by p.date, p.commodity_id
),

complete_centre_price as (  -- all centres reported that day
    select cp.date, cp.commodity_id, cp.log_price
    from centre_price as cp
    inner join n_centres as n using (commodity_id)
    where cp.n_reported = n.n
),

centre_change as (
    select date, commodity_id,
           log_price - lag(log_price) over (partition by commodity_id order by date) as chg
    from complete_centre_price
),

province_change as (
    select p.date, p.commodity_id, p.province_id,
           p.log_price - lag(p.log_price) over (
               partition by p.commodity_id, p.province_id order by p.date) as chg
    from prices as p
    where p.commodity_id in (select commodity_id from centres)
      and not exists (select 1 from centres as c
                      where c.commodity_id = p.commodity_id and c.province_id = p.province_id)
),

lags as (select range::integer as lag_days from range(0, {{ max_lag + 1 }}))

select
    pc.commodity_id,
    pc.province_id,
    l.lag_days,
    corr(pc.chg, cc.chg) as correlation,
    count(*) as n_pairs
from province_change as pc
cross join lags as l
inner join centre_change as cc
    on cc.commodity_id = pc.commodity_id
   and cc.date = pc.date - l.lag_days::integer
where pc.chg is not null and cc.chg is not null
group by all
having count(*) >= 200
