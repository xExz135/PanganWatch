-- Silver USD/IDR: one row per calendar day. ECB publishes on working days only;
-- gaps (weekends, holidays) are forward-filled from the last published rate and
-- flagged is_filled = true (spec §6 allows this for FX only).

with raw as (
    select fetched_at, payload::json -> 'rates' as rates
    from {{ ref('bronze_fx_raw') }}
    where status = 'ok' and payload is not null
),

published as (
    select
        cast(day as date) as date,
        cast(rates -> day ->> 'IDR' as double) as usd_idr,
        fetched_at
    from (select fetched_at, rates, unnest(json_keys(rates)) as day from raw)
    qualify row_number() over (partition by day order by fetched_at desc) = 1
),

calendar as (
    select cast(d as date) as date
    from generate_series(
        (select min(date) from published), (select max(date) from published), interval 1 day
    ) as t(d)
)

select
    c.date,
    p.usd_idr,
    p.date < c.date as is_filled  -- carried forward from the last published day
from calendar as c
asof left join published as p on c.date >= p.date
