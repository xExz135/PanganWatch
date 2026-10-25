-- Silver PIHPS prices: one row per date x commodity x city x market tier.
-- Responses are wide (one key per date, "dd/mm/yyyy" -> "74,850"); this unpivots them.
-- Only level-2 rows are commodities; level-1 rows are PIHPS category averages.
-- When the same key was fetched more than once, the latest fetch wins (PIHPS revises).
-- No forward-fill: a missing cell stays missing.

with raw as (
    select request_key, fetched_at, request_params, payload
    from {{ ref('bronze_pihps_raw') }}
    where status = 'ok' and payload is not null
),

rows as (
    select
        request_key,
        fetched_at,
        request_params ->> 'market_tier' as market_tier,
        cast(request_params ->> 'city_id' as integer) as city_id,
        unnest(from_json(payload::json -> 'data', '["JSON"]')) as r
    from raw
),

cells as (
    select
        request_key, fetched_at, market_tier, city_id,
        trim(r ->> 'name') as commodity_raw,
        r,
        unnest(json_keys(r)) as k
    from rows
    where cast(r ->> 'level' as integer) = 2
),

parsed as (
    select
        strptime(k, '%d/%m/%Y')::date as date,
        commodity_raw,
        city_id,
        market_tier,
        json_extract_string(r, '$."' || k || '"') as price_raw,
        fetched_at,
        request_key
    from cells
    where k not in ('no', 'name', 'level')
),

priced as (
    select
        *,
        cast(round(try_cast(replace(price_raw, ',', '') as decimal(18, 2))) as bigint)
            as price_idr_per_unit
    from parsed
),

latest as (
    select *
    from priced
    where price_idr_per_unit > 0
    qualify row_number() over (
        partition by date, commodity_raw, city_id, market_tier
        order by fetched_at desc, request_key desc
    ) = 1
),

mapped as (
    select
        l.date,
        l.commodity_raw,
        n.commodity_id,
        p.province_id,
        l.city_id,
        l.market_tier,
        l.price_idr_per_unit,
        c.unit,
        'pihps' as source,
        l.fetched_at as loaded_at,
        l.request_key
    from latest as l
    left join {{ ref('pihps_commodity_names') }} as n on n.pihps_name = l.commodity_raw
    left join {{ ref('commodities') }} as c on c.commodity_id = n.commodity_id
    left join {{ ref('pihps_cities') }} as ci on ci.city_id = l.city_id
    left join {{ ref('provinces') }} as p on p.pihps_province_id = ci.pihps_province_id
)

select
    *,
    -- Daily jump flag (spec §8): > threshold change vs the city's previous observation.
    coalesce(
        abs(
            price_idr_per_unit::double
            / lag(price_idr_per_unit) over (
                partition by commodity_raw, city_id, market_tier order by date
            ) - 1
        ) > {{ var('daily_jump_threshold') }},
        false
    ) as is_jump_flag
from mapped
