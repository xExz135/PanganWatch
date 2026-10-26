{{ config(materialized='table') }}
-- Model inputs per published day x commodity x province (traditional market, the forecast
-- target). Every column uses only data that existed by the end of `date`, with each
-- source's own delay (docs/decisions.md):
--   prices                 up to `date` (asof joins look backwards only)
--   producer / wholesale   their latest update (PIHPS: monthly / weekly)
--   weather                windows ending 15 days earlier (the last 14 days get revised)
--   food CPI               month M from the 5th of M+1
--   FX                     up to `date`
-- A forecast issued on run_date uses the latest row dated before run_date. Calendar facts of
-- the target date (known in advance) are added by ml/ at training and forecast time.
-- Log prices throughout; changes are log differences.

with px as (
    select date, commodity_id, province_id, ln(price_idr) as lp, n_cities
    from {{ ref('fct_daily_price') }}
    where market_tier = 'traditional' and not is_imputed
),

-- --- own price history ---------------------------------------------------------------------
step as (
    select
        *,
        lp - lag(lp) over w as chg_1,
        date - lag(date) over w as gap_days
    from px
    window w as (partition by commodity_id, province_id order by date)
),

runs as (
    select *, sum((coalesce(chg_1, 0) <> 0)::int) over w as change_run
    from step
    window w as (partition by commodity_id, province_id order by date)
),

rolling as (
    select
        *,
        date - min(date) over (partition by commodity_id, province_id, change_run)
            as days_unchanged,
        lp - avg(lp) over r7 as dev_mean_7,
        lp - avg(lp) over r28 as dev_mean_28,
        lp - avg(lp) over r90 as dev_mean_90,
        case when stddev_samp(lp) over r28 < 1e-9 then 0.0  -- flat price (or float noise)
             else (lp - avg(lp) over r28) / stddev_samp(lp) over r28 end as zscore_28,
        lp - min(lp) over r90 as above_min_90,
        max(lp) over r90 - lp as below_max_90,
        stddev_samp(chg_1) over r28 as vol_28,
        stddev_samp(chg_1) over r90 as vol_90,
        count(*) over r28 as n_obs_28
    from runs
    window
        r7 as (partition by commodity_id, province_id order by date
               range between interval 6 day preceding and current row),
        r28 as (partition by commodity_id, province_id order by date
                range between interval 27 day preceding and current row),
        r90 as (partition by commodity_id, province_id order by date
                range between interval 89 day preceding and current row)
),

lag_dates as (
    select
        *,
        date - 7 as d7, date - 14 as d14, date - 28 as d28, date - 364 as d364
    from rolling
),

own as (
    select
        b.*,
        b.lp - l7.lp as ret_7,
        b.lp - l14.lp as ret_14,
        b.lp - l28.lp as ret_28,
        b.lp - l364.lp as ret_364
    from lag_dates as b
    asof left join px as l7
        on l7.commodity_id = b.commodity_id and l7.province_id = b.province_id
       and b.d7 >= l7.date
    asof left join px as l14
        on l14.commodity_id = b.commodity_id and l14.province_id = b.province_id
       and b.d14 >= l14.date
    asof left join px as l28
        on l28.commodity_id = b.commodity_id and l28.province_id = b.province_id
       and b.d28 >= l28.date
    asof left join px as l364
        on l364.commodity_id = b.commodity_id and l364.province_id = b.province_id
       and b.d364 >= l364.date
),

-- --- other tiers in the same province (latest update, ignored if older than ~2 cycles) ------
tiers as (
    select date, commodity_id, province_id, market_tier, ln(price_idr) as lp
    from {{ ref('fct_daily_price') }}
    where market_tier in ('producer', 'wholesale') and not is_imputed
),

producer as (select * from tiers where market_tier = 'producer'),
wholesale as (select * from tiers where market_tier = 'wholesale'),

with_tiers as (
    select
        o.*,
        case when p.date >= o.date - 62 then p.lp - o.lp end as producer_gap,
        case when p.date >= o.date - 62 and p35.date >= o.date - 97
             then p.lp - p35.lp end as producer_chg_35,
        case when w.date >= o.date - 14 then w.lp - o.lp end as wholesale_gap,
        case when w.date >= o.date - 14 and w7.date >= o.date - 21
             then w.lp - w7.lp end as wholesale_chg_7
    from own as o
    asof left join producer as p
        on p.commodity_id = o.commodity_id and p.province_id = o.province_id
       and o.date >= p.date
    asof left join producer as p35
        on p35.commodity_id = o.commodity_id and p35.province_id = o.province_id
       and o.date - 35 >= p35.date
    asof left join wholesale as w
        on w.commodity_id = o.commodity_id and w.province_id = o.province_id
       and o.date >= w.date
    asof left join wholesale as w7
        on w7.commodity_id = o.commodity_id and w7.province_id = o.province_id
       and o.d7 >= w7.date
),

-- --- national price and the producing centres ------------------------------------------------
national_daily as (
    select date, commodity_id, median(lp) as lp, count(*) as n
    from px
    group by all
),

national as (  -- days when at least 80% of the provinces usual over the past year reported
    select date, commodity_id, lp
    from national_daily
    qualify n >= 0.8 * median(n) over (
        partition by commodity_id order by date
        range between interval 365 day preceding and current row)
),

centres as (select commodity_id, province_id from {{ ref('production_centers') }}),

centre_daily as (
    select p.date, p.commodity_id, median(p.lp) as lp, count(*) as n
    from px as p
    inner join centres as c using (commodity_id, province_id)
    group by p.date, p.commodity_id
),

centre as (  -- all centres reported
    select d.date, d.commodity_id, d.lp
    from centre_daily as d
    inner join (select commodity_id, count(*) as n from centres group by all) as k
        using (commodity_id)
    where d.n = k.n
),

with_space as (
    select
        t.*,
        t.lp - n0.lp as rel_national,
        n0.lp - n7.lp as national_ret_7,
        c0.lp - c7.lp as centre_ret_7
    from with_tiers as t
    asof left join national as n0
        on n0.commodity_id = t.commodity_id and t.date >= n0.date
    asof left join national as n7
        on n7.commodity_id = t.commodity_id and t.d7 >= n7.date
    asof left join centre as c0
        on c0.commodity_id = t.commodity_id and t.date >= c0.date
    asof left join centre as c7
        on c7.commodity_id = t.commodity_id and t.d7 >= c7.date
),

-- --- weather: rolling totals and anomalies vs earlier years, used 15 days late ---------------
wx_roll as (
    select
        date,
        province_id,
        sum(rain_mm) over r7 as rain_7,
        sum(rain_mm) over r30 as rain_30,
        sum(rain_mm) over r60 as rain_60,
        avg(temp_max_c) over r30 as temp_max_30
    from {{ ref('stg_weather') }}
    window
        r7 as (partition by province_id order by date
               range between interval 6 day preceding and current row),
        r30 as (partition by province_id order by date
                range between interval 29 day preceding and current row),
        r60 as (partition by province_id order by date
                range between interval 59 day preceding and current row)
),

wx as (  -- anomaly = this window minus the same calendar window in earlier years
    select
        date,
        province_id,
        rain_7,
        rain_30 - avg(rain_30) over clim as rain_30_anomaly,
        rain_60 - avg(rain_60) over clim as rain_60_anomaly,
        temp_max_30 - avg(temp_max_30) over clim as temp_max_30_anomaly
    from wx_roll
    window clim as (partition by province_id, dayofyear(date) order by year(date)
                    rows between unbounded preceding and 1 preceding)
),

-- --- macro: FX, food CPI, fuel --------------------------------------------------------------
fx as (select date, ln(usd_idr) as lfx from {{ ref('stg_fx') }}),

cpi as (
    select month + interval 1 month + interval 4 day as available_from, mom_pct, yoy_pct
    from {{ ref('stg_cpi') }}
    where region_level = 'national' and group_code = 1552
),

fuel as (
    select effective_date
    from {{ ref('fuel_price_events') }}
    where is_subsidized
)

select
    s.date,
    s.commodity_id,
    s.province_id,
    s.lp as log_price,
    s.n_cities,
    s.gap_days,
    s.chg_1,
    s.ret_7,
    s.ret_14,
    s.ret_28,
    s.ret_364,
    s.dev_mean_7,
    s.dev_mean_28,
    s.dev_mean_90,
    s.zscore_28,
    s.above_min_90,
    s.below_max_90,
    s.vol_28,
    s.vol_90,
    s.n_obs_28,
    s.days_unchanged,
    s.producer_gap,
    s.producer_chg_35,
    s.wholesale_gap,
    s.wholesale_chg_7,
    s.rel_national,
    s.national_ret_7,
    s.centre_ret_7,
    w.rain_7,
    w.rain_30_anomaly,
    w.rain_60_anomaly,
    w.temp_max_30_anomaly,
    f0.lfx - f28.lfx as fx_ret_28,
    c.mom_pct as cpi_food_mom,
    c.yoy_pct as cpi_food_yoy,
    coalesce(least(s.date - fu.effective_date, 730), 730) as days_since_fuel_change,
    d.is_ramadan,
    d.days_to_lebaran,
    d.days_to_idul_adha,
    d.is_school_holiday,
    m.perishability_days,
    m.is_imported
from with_space as s
left join wx as w
    on w.province_id = s.province_id and w.date = s.date - 15
asof left join fx as f0 on s.date >= f0.date
asof left join fx as f28 on s.d28 >= f28.date
asof left join cpi as c on s.date >= c.available_from
asof left join fuel as fu on s.date >= fu.effective_date
inner join {{ ref('dim_date') }} as d on d.date = s.date
inner join {{ ref('dim_commodity') }} as m on m.commodity_id = s.commodity_id
