-- Central fact: one row per date x commodity x province x market tier, on days PIHPS
-- published. Province price = median of the cities that reported that day (robust to one
-- bad city); n_cities shows how thin that is. No imputation here, so is_imputed is false;
-- downstream imputation must add its own flagged rows.
-- price_bapanas / source_gap_pct stay NULL until the optional Bapanas source exists.

select
    date,
    commodity_id,
    province_id,
    market_tier,
    cast(round(median(price_idr_per_unit)) as bigint) as price_idr,
    count(*) as n_cities,
    false as is_imputed,
    cast(null as bigint) as price_bapanas,
    cast(null as double) as source_gap_pct
from {{ ref('stg_pihps_price') }}
where commodity_id is not null and province_id is not null
group by all
