-- Bronze PIHPS: every saved response, exactly as received, joined to its manifest row.
-- Never parsed here. One row per request.
{{ config(materialized='view') }}

with manifest as (
    select *
    from read_json(
        '{{ var("bronze_root") }}/pihps/_manifest.jsonl',
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
    from read_text('{{ var("bronze_root") }}/pihps/*/*.json')
)

select
    m.request_key,
    'pihps' as source,
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
    on ends_with(f.filename, '/' || m.file_path)  -- file_path is relative to bronze root
