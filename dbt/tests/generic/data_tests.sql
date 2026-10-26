{# Custom generic tests for PanganWatch (spec §8). Each returns the failing rows. #}

{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}


{% test price_within_bounds(model, column_name) %}
-- Price between the min and max for its commodity group (seed price_bounds.csv).
select m.*
from {{ model }} as m
join {{ ref('commodities') }} as c using (commodity_id)
join {{ ref('price_bounds') }} as b using (commodity_group)
where m.{{ column_name }} < b.min_price_idr or m.{{ column_name }} > b.max_price_idr
{% endtest %}


{% test is_false(model, column_name) %}
select * from {{ model }} where {{ column_name }}
{% endtest %}


{% test fresh_within_working_days(model, column_name) %}
-- Fails when more than N publishing days (no weekends/holidays) passed since the latest
-- date. Off unless PANGANWATCH_ENFORCE_FRESHNESS=true (the sample DB is old on purpose).
{% if var('enforce_freshness') | string | lower == 'true' %}
with latest as (select max({{ column_name }}) as d from {{ model }})
select latest.d, count(*) as missed_publishing_days
from latest
join {{ ref('dim_date') }} as dd
    on dd.date > latest.d and dd.date <= current_date and dd.is_publishing_day
group by latest.d
having count(*) > {{ var('max_working_days_stale') }}
{% else %}
select 1 where false
{% endif %}
{% endtest %}


{% test province_coverage(model) %}
-- Each v1 commodity reported (traditional tier) by >= coverage_min_share of provinces
-- on the latest published date.
with latest as (select max(date) as d from {{ model }}),
n_prov as (select count(*) as n from {{ ref('provinces') }})
select f.commodity_id, count(distinct f.province_id) as provinces, n_prov.n as total
from {{ model }} as f
join latest on f.date = latest.d
join {{ ref('commodities') }} as c on c.commodity_id = f.commodity_id and c.is_v1
cross join n_prov
where f.market_tier = 'traditional'
group by f.commodity_id, n_prov.n
having count(distinct f.province_id) < {{ var('coverage_min_share') }} * n_prov.n
{% endtest %}


{% test row_count_stable(model, date_column='date') %}
-- Latest date's row count within +/- row_count_tolerance of the average over the previous
-- 28 calendar days (published days only, since PIHPS skips weekends).
with daily as (
    select {{ date_column }} as d, count(*) as n from {{ model }} group by 1
),
latest as (select max(d) as d from daily),
baseline as (
    select avg(n) as avg_n
    from daily, latest
    where daily.d < latest.d and daily.d >= latest.d - 28
)
select daily.d, daily.n, baseline.avg_n
from daily
join latest on daily.d = latest.d
cross join baseline
where baseline.avg_n is not null
  and abs(daily.n / baseline.avg_n - 1) > {{ var('row_count_tolerance') }}
{% endtest %}


{% test source_gap_within(model, column_name) %}
-- PIHPS vs Bapanas gap above the threshold (spec §8). Passes trivially while Bapanas
-- (optional source S2) is not ingested and the column is NULL.
select *
from {{ model }}
where abs({{ column_name }}) > {{ var('source_gap_max') }}
{% endtest %}


{% test tier_order(model) %}
-- producer <= wholesale <= retail, on national monthly medians per commodity.
-- Days, cities and even province-months often break the order in real PIHPS data
-- (docs/source_notes.md), so only the national month is checked. Flags a month where a tier
-- sits more than tier_order_tolerance above the next tier up; a swapped tier or a unit
-- error flags most months (812 of 1,218 with producer and retail swapped).
with monthly as (
    select
        commodity_id,
        date_trunc('month', date) as month,
        median(producer_price) as producer_price,
        median(wholesale_price) as wholesale_price,
        median(retail_price) as retail_price
    from {{ model }}
    where producer_price is not null and wholesale_price is not null
    group by all
)

select *
from monthly
where producer_price > wholesale_price * (1 + {{ var('tier_order_tolerance') }})
    or wholesale_price > retail_price * (1 + {{ var('tier_order_tolerance') }})
{% endtest %}
