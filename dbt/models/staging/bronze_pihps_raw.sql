-- Bronze PIHPS: one row per request, payload exactly as received. Never parsed here.
{{ config(materialized='view') }}
{{ bronze_view('pihps') }}
