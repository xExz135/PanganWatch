{{ config(materialized='table') }}
-- A6 volatility and risk ranking, per commodity nationally and per province (traditional tier).
--   volatility_daily  SD of daily log price changes over the whole history
--   volatility_90d    the same over the last 90 days (calm or stormy now vs usual)
--   spike_share       share of days followed by a rise of 15%+ within 14 days (the same
--                     definition as the spike label in data-scientist.md)
--   risk_segment      high: spike_share >= 10%, medium: >= 1%, low: below
-- Changes across a gap of more than 7 days (a paused series) are skipped. A province series
-- with a median of one reporting city is flagged is_thin: one market's noise, not a province.
-- Series with fewer than 60 measurable days are left out.
{% set spike_rise = 0.15 %}
{% set spike_days = 14 %}
{% set high_share = 0.10 %}
{% set medium_share = 0.01 %}
{% set min_days = 60 %}

with series as (
    select
        'national' as geo_level, null::integer as province_id, commodity_id, date, price_idr,
        n_provinces::double as n_reporting
    from {{ ref('ana_national_price') }}
    union all
    select
        'province' as geo_level, province_id, commodity_id, date, price_idr,
        n_cities::double as n_reporting
    from {{ ref('fct_daily_price') }}
    where market_tier = 'traditional' and not is_imputed
),

changes as (
    select
        *,
        ln(price_idr / lag(price_idr) over w) as dlog,
        date - lag(date) over w as gap_days,
        max(price_idr) over (
            partition by geo_level, commodity_id, province_id order by date
            range between interval 1 day following and interval {{ spike_days }} day following
        ) as max_next
    from series
    window w as (partition by geo_level, commodity_id, province_id order by date)
),

last_day as (select max(date) as d from series),

stats as (
    select
        c.geo_level,
        c.commodity_id,
        c.province_id,
        stddev(c.dlog) filter (where c.gap_days <= 7) as volatility_daily,
        stddev(c.dlog) filter (where c.gap_days <= 7 and c.date > l.d - 90) as volatility_90d,
        avg((c.max_next >= {{ 1 + spike_rise }} * c.price_idr)::int)
            filter (where c.date <= l.d - {{ spike_days }}) as spike_share,
        count(*) filter (where c.max_next >= {{ 1 + spike_rise }} * c.price_idr
                           and c.date <= l.d - {{ spike_days }}) as spike_days,
        count(*) filter (where c.date <= l.d - {{ spike_days }} and c.max_next is not null)
            as n_days,
        median(c.n_reporting) as median_reporting
    from changes as c
    cross join last_day as l
    group by all
)

select
    *,
    geo_level = 'province' and median_reporting < 2 as is_thin,
    case
        when spike_share >= {{ high_share }} then 'high'
        when spike_share >= {{ medium_share }} then 'medium'
        else 'low'
    end as risk_segment
from stats
where n_days >= {{ min_days }}  -- too short a series to rank
