-- Farm-to-table chain per date x commodity x province. Retail = traditional market.
-- Any tier may be missing on a day (producer coverage is thinner); ratios are NULL then.
-- A1 should use only rows where all three prices exist ("matched province-days").

with pivoted as (
    select
        date,
        commodity_id,
        province_id,
        max(price_idr) filter (where market_tier = 'producer') as producer_price,
        max(price_idr) filter (where market_tier = 'wholesale') as wholesale_price,
        max(price_idr) filter (where market_tier = 'traditional') as retail_price
    from {{ ref('fct_daily_price') }}
    group by all
)

select
    date,
    commodity_id,
    province_id,
    producer_price,
    wholesale_price,
    retail_price,
    producer_price::double / nullif(retail_price, 0) as farm_share_pct,
    wholesale_price::double / nullif(producer_price, 0) - 1 as wholesale_markup_pct,
    retail_price::double / nullif(wholesale_price, 0) - 1 as retail_markup_pct
from pivoted
where retail_price is not null
