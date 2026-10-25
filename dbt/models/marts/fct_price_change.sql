-- Price changes and volatility per series. PIHPS skips weekends and holidays, so:
--   chg_1d_pct  = change vs the previous published day
--   chg_7d_pct  = change vs the latest price on or before date - 7 calendar days
--   chg_28d_pct = same, 28 calendar days
-- A look-back price older than `stale` extra days (e.g. across the Lebaran break) gives NULL.
-- Rolling stats use a 28-calendar-day window and need at least 10 observations.

{% set stale = 7 %}

with p as (
    select date, commodity_id, province_id, market_tier, price_idr
    from {{ ref('fct_daily_price') }}
),

base as (
    select
        *,
        lag(price_idr) over w as prev_price,
        ln(price_idr) - ln(lag(price_idr) over w) as log_chg_1d
    from p
    window w as (partition by commodity_id, province_id, market_tier order by date)
),

with_7d as (
    select b.*, a.price_idr as price_7d, a.date as date_7d
    from base as b
    asof left join p as a
        on b.commodity_id = a.commodity_id
        and b.province_id = a.province_id
        and b.market_tier = a.market_tier
        and b.date - 7 >= a.date
),

with_28d as (
    select b.*, a.price_idr as price_28d, a.date as date_28d
    from with_7d as b
    asof left join p as a
        on b.commodity_id = a.commodity_id
        and b.province_id = a.province_id
        and b.market_tier = a.market_tier
        and b.date - 28 >= a.date
),

rolled as (
    select
        *,
        count(*) over r28 as n_obs_28d,
        stddev_samp(log_chg_1d) over r28 as vol_28d,
        avg(price_idr) over r28 as mean_28d,
        stddev_samp(price_idr) over r28 as sd_28d
    from with_28d
    window r28 as (
        partition by commodity_id, province_id, market_tier
        order by date
        range between interval 27 days preceding and current row
    )
)

select
    date,
    commodity_id,
    province_id,
    market_tier,
    price_idr,
    price_idr::double / prev_price - 1 as chg_1d_pct,
    case when date - date_7d <= 7 + {{ stale }} then price_idr::double / price_7d - 1 end
        as chg_7d_pct,
    case when date - date_28d <= 28 + {{ stale }} then price_idr::double / price_28d - 1 end
        as chg_28d_pct,
    case when n_obs_28d >= 10 then vol_28d end as rolling_28d_volatility,
    case when n_obs_28d >= 10 and sd_28d > 0 then (price_idr - mean_28d) / sd_28d end
        as zscore_28d
from rolled
