{#
  Bronze view for one source: every saved response, exactly as received, joined to its
  manifest row. Bronze lives on disk as raw files + an append-only _manifest.jsonl
  (docs/decisions.md). file_path in the manifest is relative to the bronze root.
  A source that has never been fetched gives an empty view (not an error), so a fresh
  checkout can build with only some sources present.
#}
{% macro bronze_view(source) %}
{%- set root = var("bronze_root") ~ "/" ~ source -%}
{%- set present = false -%}
{%- if execute -%}
    {%- set check = run_query(
        "select (select count(*) from glob('" ~ root ~ "/_manifest.jsonl'))"
        ~ " * (select count(*) from glob('" ~ root ~ "/*/*.json'))"
    ) -%}
    {%- set present = check.columns[0].values()[0] > 0 -%}
{%- endif %}
{% if present %}
with manifest as (
    select *
    from read_json(
        '{{ root }}/_manifest.jsonl',
        format = 'newline_delimited',
        columns = {
            request_key: 'VARCHAR', kind: 'VARCHAR', params: 'JSON', status: 'VARCHAR',
            http_status: 'INTEGER', file_path: 'VARCHAR', n_rows: 'INTEGER',
            error: 'VARCHAR', fetched_at: 'TIMESTAMPTZ'
        }
    )
),

files as (
    select replace(filename, '\', '/') as filename, content
    from read_text('{{ root }}/*/*.json')
)

select
    m.request_key,
    '{{ source }}' as source,
    m.kind,
    m.params as request_params,
    m.fetched_at,
    m.http_status,
    m.status,
    m.n_rows,
    m.error,
    m.file_path,
    f.content as payload
from manifest as m
left join files as f
    on ends_with(f.filename, '/' || m.file_path)
{% else %}
-- no {{ source }} data fetched yet: empty, correctly typed
select
    cast(null as varchar) as request_key,
    '{{ source }}' as source,
    cast(null as varchar) as kind,
    cast(null as json) as request_params,
    cast(null as timestamptz) as fetched_at,
    cast(null as integer) as http_status,
    cast(null as varchar) as status,
    cast(null as integer) as n_rows,
    cast(null as varchar) as error,
    cast(null as varchar) as file_path,
    cast(null as varchar) as payload
where false
{% endif %}
{% endmacro %}
