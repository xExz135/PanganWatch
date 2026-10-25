-- Bronze BPS: one row per table x year fetch, payload exactly as received.
{{ config(materialized='view') }}
{{ bronze_view('bps') }}
