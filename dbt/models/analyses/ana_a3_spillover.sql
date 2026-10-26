{{ config(materialized='table') }}
-- A3 summary per commodity and non-centre province: the same-day correlation with the
-- production centres, the lag (0-21 days) with the highest correlation, and the distance to
-- the nearest centre. A lag is reported only where the link is clear (best correlation of at
-- least 0.2; pure noise over 22 lags rarely exceeds 0.1 with ~1,000 days). Provinces with a
-- median of one reporting city are flagged is_thin.
{% set clear_link = 0.2 %}

with best as (
    select commodity_id, province_id,
           arg_max(lag_days, correlation) as best_lag_days,
           max(correlation) as best_correlation,
           max(correlation) filter (where lag_days = 0) as same_day_correlation,
           max(n_pairs) as n_pairs
    from {{ ref('ana_a3_spillover_lags') }}
    group by all
),

distance as (
    select c.commodity_id, p.province_id,
           min(2 * 6371 * asin(sqrt(
               pow(sin(radians(q.lat - p.lat) / 2), 2)
               + cos(radians(p.lat)) * cos(radians(q.lat))
                 * pow(sin(radians(q.lon - p.lon) / 2), 2)))) as km_to_nearest_centre
    from {{ ref('dim_province') }} as p
    cross join {{ ref('production_centers') }} as c
    inner join {{ ref('dim_province') }} as q on q.province_id = c.province_id
    group by all
),

reporting as (
    select commodity_id, province_id, median(n_cities) as median_cities
    from {{ ref('fct_daily_price') }}
    where market_tier = 'traditional'
    group by all
)

select
    b.commodity_id,
    b.province_id,
    b.same_day_correlation,
    b.best_correlation,
    case when b.best_correlation >= {{ clear_link }} then b.best_lag_days end as lag_days,
    b.best_correlation >= {{ clear_link }} as has_clear_link,
    d.km_to_nearest_centre,
    r.median_cities < 2 as is_thin,
    b.n_pairs
from best as b
inner join distance as d using (commodity_id, province_id)
inner join reporting as r using (commodity_id, province_id)
