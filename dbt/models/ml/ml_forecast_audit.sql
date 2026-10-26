-- Checks on fct_forecast, which ml.forecast writes (not dbt). Before the first forecast the
-- table doesn't exist yet, so this returns no rows instead of failing the build.
{% set rel = adapter.get_relation(database=target.database, schema=target.schema,
                                  identifier='fct_forecast') %}
{% if rel %}
select
    *,
    target_date <> run_date + horizon_days as bad_target_date,
    not (q10 <= q50 and q50 <= q90) as bad_quantile_order,
    -- ledger integrity: a forecast must exist by the end of its run_date (WIB), never later
    (created_at + interval 7 hour)::date > run_date as written_after_run_date
from {{ rel }}
{% else %}
select
    null::date as run_date, null::date as target_date, null::integer as horizon_days,
    null::varchar as commodity_id, null::integer as province_id, null::varchar as model_version,
    null::bigint as q10, null::bigint as q50, null::bigint as q90, null::timestamp as created_at,
    false as bad_target_date, false as bad_quantile_order, false as written_after_run_date
where false
{% endif %}
