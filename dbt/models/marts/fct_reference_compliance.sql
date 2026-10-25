-- Retail price vs the government reference in force that day, per date x commodity x
-- province x retail tier. Only days that have both a PIHPS price and a reference are kept
-- (no reference = no row). Reference ranges are compared on their upper bound.
-- consecutive_days_above counts published days in a row above the reference
-- (PIHPS skips weekends and holidays), 0 when not above.

with retail as (
    select date, commodity_id, province_id, market_tier, price_idr
    from {{ ref('fct_daily_price') }}
    -- consumer references apply to retail sales: traditional markets and modern retail
    where market_tier in ('traditional', 'modern')
),

joined as (
    select
        r.date,
        r.commodity_id,
        r.province_id,
        r.market_tier,
        r.price_idr as retail_price,
        ref.price_idr as reference_price,
        ref.price_type,
        ref.regulation,
        r.price_idr::double / ref.price_idr - 1 as pct_above,
        r.price_idr > ref.price_idr as is_above
    from retail as r
    join {{ ref('dim_reference_price') }} as ref
        on ref.commodity_id = r.commodity_id
        and ref.province_id = r.province_id
        and r.date between ref.valid_from and coalesce(ref.valid_to, date '9999-12-31')
),

runs as (
    select
        *,
        -- each day at or below the reference starts a new run
        sum(case when is_above then 0 else 1 end) over (
            partition by commodity_id, province_id, market_tier
            order by date rows between unbounded preceding and current row
        ) as run_id
    from joined
)

select
    date,
    commodity_id,
    province_id,
    market_tier,
    retail_price,
    reference_price,
    price_type,
    regulation,
    pct_above,
    is_above,
    case
        when is_above then count(*) filter (where is_above) over (
            partition by commodity_id, province_id, market_tier, run_id
            order by date rows between unbounded preceding and current row
        )
        else 0
    end as consecutive_days_above
from runs
