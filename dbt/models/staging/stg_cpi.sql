-- Silver CPI (BPS): one row per month x region x expenditure group x CPI base year.
-- BPS packs each value under one key: region || table || group || year || month
-- (e.g. '1' '2212' '1551' '125' '1'). We split the key at table||group, check the
-- region against the table's own region list, and pivot index / m-o-m / y-o-y side by side.
-- Percentages are stored as decimals (3.79 % -> 0.0379).

{% set groups = var('bps_groups') %}

with raw as (
    select request_key, fetched_at, request_params as p, payload::json as j
    from {{ ref('bronze_bps_raw') }}
    where status = 'ok' and payload is not null
),

docs as (
    select
        request_key,
        fetched_at,
        p ->> 'var_id' as var_id,
        p ->> 'measure' as measure,
        cast(p ->> 'base_year' as integer) as base_year,
        p ->> 'level' as level,
        j -> 'tahun' -> 0 ->> 'val' as tahun_val,
        cast(j -> 'tahun' -> 0 ->> 'label' as integer) as year,
        cast(j -> 'datacontent' as map(varchar, double)) as dc,
        j -> 'vervar' as vervar
    from raw
),

kv as (
    select
        * exclude (dc, vervar),
        unnest(map_keys(dc)) as k,
        unnest(map_values(dc)) as v
    from docs
),

split as (
    select
        kv.*,
        g.group_code,
        strpos(k, var_id || g.group_code::varchar) as pos
    from kv
    cross join (select unnest({{ groups | list }}) as group_code) as g
    where strpos(k, var_id || g.group_code::varchar) > 0
),

decoded as (
    select
        *,
        left(k, pos - 1) as region_val,
        substr(k, pos + length(var_id) + 4) as rest
    from split
),

regions as (
    select distinct
        request_key,
        unnest(from_json(vervar, '["JSON"]')) ->> 'val' as region_val,
        unnest(from_json(vervar, '["JSON"]')) ->> 'label' as region_label
    from docs
),

cells as (
    select
        make_date(d.year, cast(substr(d.rest, length(d.tahun_val) + 1) as integer), 1) as month,
        d.base_year,
        case when upper(r.region_label) = 'INDONESIA' then 'national' else d.level end
            as region_level,
        d.region_val,
        upper(trim(r.region_label)) as region_name,
        d.group_code,
        d.measure,
        d.v as value,
        d.fetched_at
    from decoded as d
    join regions as r on r.request_key = d.request_key and r.region_val = d.region_val
    where starts_with(d.rest, d.tahun_val)
      and cast(substr(d.rest, length(d.tahun_val) + 1) as integer) between 1 and 12
      -- the national row also appears in province tables; keep it from city tables only
      and not (d.level = 'province' and upper(r.region_label) = 'INDONESIA')
),

latest as (
    select *
    from cells
    qualify row_number() over (
        partition by month, base_year, region_level, region_val, group_code, measure
        order by fetched_at desc
    ) = 1
),

pivoted as (
    select
        month, base_year, region_level, region_val, region_name, group_code,
        max(value) filter (where measure = 'index') as index_value,
        max(value) filter (where measure = 'mom') / 100 as mom_pct,
        max(value) filter (where measure = 'yoy') / 100 as yoy_pct
    from latest
    group by all
),

with_yoy as (
    -- 2018-base tables have no y-o-y table: derive it from the index 12 months earlier
    select
        p.* exclude (yoy_pct),
        coalesce(p.yoy_pct, p.index_value / nullif(prev.index_value, 0) - 1) as yoy_pct
    from pivoted as p
    left join pivoted as prev
        on prev.base_year = p.base_year
        and prev.region_level = p.region_level
        and prev.region_val = p.region_val
        and prev.group_code = p.group_code
        and prev.month = p.month - interval 12 month
),

pihps_city as (
    select
        city_id,
        p.province_id,
        upper(replace(trim(city_name), 'Kab. ', 'Kab ')) as norm_name
    from {{ ref('pihps_cities') }}
    join {{ ref('provinces') }} as p using (pihps_province_id)
),

mapped as (
    select
        c.*,
        -- PIHPS city when the BPS city name matches one (exact, or with KOTA/KAB added)
        coalesce(m1.city_id, m2.city_id, m3.city_id) as city_id,
        case
            when c.region_level = 'national' then null
            -- 2018-base cities and all provinces carry BPS codes: first 2 digits = province
            when c.base_year = 2018 or c.region_level = 'province'
                then try_cast(left(c.region_val, 2) as integer)
            else coalesce(m1.province_id, m2.province_id, m3.province_id)
        end as code_province
    from with_yoy as c
    left join pihps_city as m1
        on c.region_level = 'city' and m1.norm_name = c.region_name
    left join pihps_city as m2
        on c.region_level = 'city' and m2.norm_name = 'KOTA ' || c.region_name
    left join pihps_city as m3
        on c.region_level = 'city' and m3.norm_name = 'KAB ' || c.region_name
)

select
    m.month,
    m.city_id,
    m.group_code,
    m.index_value,
    m.mom_pct,
    m.yoy_pct,
    m.region_level,
    m.region_val as bps_region_code,
    m.region_name,
    -- NULL for the 2022 Papua split provinces (92, 95-97), which PIHPS doesn't have
    p.province_id,
    m.base_year,
    'bps' as source
from mapped as m
left join {{ ref('provinces') }} as p on p.province_id = m.code_province
