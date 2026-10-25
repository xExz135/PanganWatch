-- Bronze weather (Open-Meteo): one row per province x date-range fetch, as received.
{{ config(materialized='view') }}
{{ bronze_view('weather') }}
