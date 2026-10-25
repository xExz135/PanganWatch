-- is_cpi_city is NULL until the BPS CPI source is ingested (Week 3).
select
    c.city_id,
    c.city_name as name,
    p.province_id,
    cast(null as boolean) as is_cpi_city,
    c.has_traditional,
    c.has_modern,
    c.has_wholesale,
    c.has_producer
from {{ ref('pihps_cities') }} as c
left join {{ ref('provinces') }} as p using (pihps_province_id)
