{{ config(materialized='table') }}
-- A5 event study: national traditional-market price around each Lebaran, detrended and indexed.
-- event_day 0 = Lebaran (Idul Fitri); negative = days before. Ramadan starts at day -30/-29.
--   national price = median across provinces, days with thin coverage dropped
--                    (ana_national_price)
--   trend          = centered 365-day rolling median, so a slow inflation trend or a long
--                    price cycle is not mistaken for a Lebaran effect
--   index          = 100 x (price / trend), rebased so the week around day -60 averages 100
-- Only Lebarans with the full -63..+30 window inside the price history are included.

with national as (
    select date, commodity_id, price_idr, n_provinces
    from {{ ref('ana_national_price') }}
),

trend as (
    select
        *,
        median(price_idr) over w as trend_price_idr,
        count(*) over w as n_trend_days
    from national
    window w as (
        partition by commodity_id order by date
        range between interval 182 day preceding and interval 182 day following
    )
),

lebarans as (
    select date as lebaran_date, year(date) as lebaran_year
    from {{ ref('dim_date') }}
    where days_to_lebaran = 0
      and date - 63 >= (select min(date) from national)
      and date + 30 <= (select max(date) from national)
),

events as (
    select
        t.commodity_id,
        l.lebaran_year,
        l.lebaran_date,
        t.date,
        datediff('day', l.lebaran_date, t.date) as event_day,
        t.price_idr,
        t.trend_price_idr,
        t.n_provinces,
        t.price_idr / t.trend_price_idr as detrended
    from lebarans as l
    inner join trend as t
        on t.date between l.lebaran_date - 63 and l.lebaran_date + 30
    where t.n_trend_days >= 100  -- too little history around this date for a trend
),

base as (
    select commodity_id, lebaran_year, avg(detrended) as base_detrended
    from events
    where event_day between -63 and -57
    group by all
)

select
    e.commodity_id,
    e.lebaran_year,
    e.lebaran_date,
    e.date,
    e.event_day,
    d.is_ramadan,
    e.price_idr,
    e.trend_price_idr::bigint as trend_price_idr,
    e.n_provinces,
    100 * e.detrended / b.base_detrended as index_value
from events as e
inner join base as b using (commodity_id, lebaran_year)
inner join {{ ref('dim_date') }} as d on d.date = e.date
where e.event_day between -60 and 30
