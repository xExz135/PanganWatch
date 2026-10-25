-- is_production_center: true if the province is a main producer of any v1 commodity.
-- production_center_commodities lists which ones (per-commodity detail for A3 and features).
select
    p.province_id,
    p.province_name as name,
    p.island_group,
    p.bps_code,
    p.lat,
    p.lon,
    p.pihps_province_id,
    count(pc.commodity_id) > 0 as is_production_center,
    list(pc.commodity_id order by pc.commodity_id) filter (where pc.commodity_id is not null)
        as production_center_commodities
from {{ ref('provinces') }} as p
left join {{ ref('production_centers') }} as pc using (province_id)
group by all
