-- Bronze FX (Frankfurter / ECB): one row per date-range fetch, as received.
{{ config(materialized='view') }}
{{ bronze_view('fx') }}
