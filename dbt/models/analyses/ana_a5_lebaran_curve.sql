{{ config(materialized='table') }}
-- A5 chart data: per commodity and event day, the median index across Lebaran years and
-- the min-max band. PIHPS skips weekends and holidays, so each day has 3-5 years behind it.

select
    commodity_id,
    event_day,
    median(index_value) as index_median,
    min(index_value) as index_min,
    max(index_value) as index_max,
    count(*) as n_years
from {{ ref('ana_a5_lebaran_daily') }}
group by all
