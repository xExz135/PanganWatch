{#
  Bronze view for one source: every saved response, exactly as received, joined to its
  manifest row. Bronze lives on disk as raw files + an append-only _manifest.jsonl
  (docs/decisions.md). file_path in the manifest is relative to the bronze root.
#}
{% macro bronze_view(source) %}
with manifest as (
    select *
    from read_json(
        '{{ var("bronze_root") }}/{{ source }}/_manifest.jsonl',
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
    from read_text('{{ var("bronze_root") }}/{{ source }}/*/*.json')
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
{% endmacro %}
