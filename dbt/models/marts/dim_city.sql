-- is_cpi_city: the city is one of BPS's 150 CPI cities (2022=100 base), matched by name.
select
    c.city_id,
    c.city_name as name,
    p.province_id,
    c.city_id in (
        select city_id from {{ ref('stg_cpi') }}
        where region_level = 'city' and base_year = 2022 and city_id is not null
    ) as is_cpi_city,
    c.has_traditional,
    c.has_modern,
    c.has_wholesale,
    c.has_producer
from {{ ref('pihps_cities') }} as c
left join {{ ref('provinces') }} as p using (pihps_province_id)
