select
    c.commodity_id,
    c.name_id,
    c.name_en,
    c.commodity_group as "group",
    c.unit,
    c.perishability_days,
    c.is_imported,
    c.is_v1,
    list(n.pihps_name order by n.pihps_name) as pihps_names
from {{ ref('commodities') }} as c
left join {{ ref('pihps_commodity_names') }} as n using (commodity_id)
group by all
