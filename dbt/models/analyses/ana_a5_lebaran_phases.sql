{{ config(materialized='table') }}
-- A5 summary: average index per phase of the Lebaran cycle, per year, then the median and
-- the range across years. 100 = the price trend two months before Lebaran.

with phased as (
    select
        commodity_id,
        lebaran_year,
        case
            when event_day between -60 and -46 then 1
            when event_day between -45 and -31 then 2
            when event_day between -30 and -23 then 3
            when event_day between -22 and -8 then 4
            when event_day between -7 and -1 then 5
            when event_day between 0 and 13 then 6
            else 7
        end as phase_order,
        index_value
    from {{ ref('ana_a5_lebaran_daily') }}
),

per_year as (
    select commodity_id, lebaran_year, phase_order, avg(index_value) as index_value
    from phased
    group by all
)

select
    commodity_id,
    phase_order,
    case phase_order
        when 1 then '60-46 days before'
        when 2 then '45-31 days before'
        when 3 then 'Ramadan week 1'
        when 4 then 'Ramadan weeks 2-3'
        when 5 then 'Last week before Lebaran'
        when 6 then 'Lebaran + 0-13 days'
        else 'Lebaran + 14-30 days'
    end as phase,
    median(index_value) as index_median,
    min(index_value) as index_min,
    max(index_value) as index_max,
    count(*) as n_years
from per_year
group by all
