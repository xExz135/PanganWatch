-- Silver weather: one row per date x province (one point per province, its capital).
-- Open-Meteo returns parallel arrays (time[], precipitation_sum[], ...); unnesting them
-- in one select zips them. Latest fetch wins (recent days are revised).

with raw as (
    select
        fetched_at,
        cast(request_params ->> 'province_id' as integer) as province_id,
        payload::json -> 'daily' as d
    from {{ ref('bronze_weather_raw') }}
    where status = 'ok' and payload is not null
),

days as (
    select
        fetched_at,
        province_id,
        unnest(from_json(d -> 'time', '["VARCHAR"]')) as day,
        unnest(from_json(d -> 'precipitation_sum', '["DOUBLE"]')) as rain_mm,
        unnest(from_json(d -> 'temperature_2m_mean', '["DOUBLE"]')) as temp_mean_c,
        unnest(from_json(d -> 'temperature_2m_max', '["DOUBLE"]')) as temp_max_c
    from raw
)

select
    cast(day as date) as date,
    province_id,
    rain_mm,
    temp_mean_c,
    temp_max_c,
    fetched_at as loaded_at
from days
where rain_mm is not null or temp_mean_c is not null
qualify row_number() over (partition by day, province_id order by fetched_at desc) = 1
