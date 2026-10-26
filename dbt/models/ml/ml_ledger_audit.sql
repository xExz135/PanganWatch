-- Checks on fct_forecast_ledger, which ml.ledger writes. Empty until the first scoring run.
{% set ledger = adapter.get_relation(database=target.database, schema=target.schema,
                                     identifier='fct_forecast_ledger') %}
{% set forecast = adapter.get_relation(database=target.database, schema=target.schema,
                                       identifier='fct_forecast') %}
{% if ledger and forecast %}
select
    l.*,
    f.run_date is null as no_matching_forecast,
    -- scored only once the target day was over (WIB)
    (l.scored_at + interval 7 hour)::date <= l.target_date as scored_too_early,
    f.run_date is not null and (
        l.abs_error <> abs(f.q50 - l.actual_price)
        or l.in_interval_80 <> (l.actual_price between f.q10 and f.q90)
    ) as error_mismatch
from {{ ledger }} l
left join {{ forecast }} f
  on f.run_date = l.run_date and f.model_version = l.model_version
 and f.commodity_id = l.commodity_id and f.province_id = l.province_id
 and f.horizon_days = l.horizon_days
{% else %}
select
    null::date as run_date, null::date as target_date, null::integer as horizon_days,
    null::varchar as commodity_id, null::integer as province_id, null::varchar as model_version,
    null::bigint as actual_price, null::bigint as abs_error, null::double as pct_error,
    null::boolean as in_interval_80, null::timestamp as scored_at,
    false as no_matching_forecast, false as scored_too_early, false as error_mismatch
where false
{% endif %}
