{{ config(materialized='table') }}
-- A4 per commodity, province and market tier over the whole history: days above the
-- reference, the longest run of published days above it, and the run still going on the
-- last day. Streaks come from fct_reference_compliance (published days, across regulation
-- changes while the price stays above the new reference).

with c as (select * from {{ ref('fct_reference_compliance') }}),

last_row as (
    select commodity_id, province_id, market_tier, consecutive_days_above as current_streak_days
    from c
    qualify row_number() over (partition by commodity_id, province_id, market_tier
                               order by date desc) = 1
)

select
    c.commodity_id,
    c.province_id,
    c.market_tier,
    min(c.date) as first_date,
    max(c.date) as last_date,
    count(*) as n_days,
    count(*) filter (where c.is_above) as days_above,
    avg(c.is_above::int) as share_above,
    max(c.consecutive_days_above) as longest_streak_days,
    any_value(l.current_streak_days) as current_streak_days,
    median(c.pct_above) filter (where c.is_above) as median_excess_when_above
from c
inner join last_row as l using (commodity_id, province_id, market_tier)
group by c.commodity_id, c.province_id, c.market_tier
