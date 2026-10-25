# Requests to the project owner

Questions about spec, scope, contract or dependencies. Each role edits only its own section (TEAM.md §6). The owner answers inline.

## Data Engineer

1. **Owner action — BPS API key.** ~~Register at webapi.bps.go.id~~ Done 2026-10-25; key in local `.env` (tested OK) and in the GitHub Actions secret `BPS_API_KEY`.
2. **Owner action — verify the calendar.** `dbt/seeds/calendar_events.csv` and `school_holidays.csv` were typed from memory; every row is `verified=false`. Check Ramadan, Lebaran and Idul Adha dates against each year's SKB and flip `verified` to true. 2027 rows are provisional.
3. **Contract — `fetch()` signature.** Spec §7 says `fetch(date_from, date_to, market_tier, province_code)`. PIHPS averages multi-city selections, so it is `fetch(client, date_from, date_to, market_tier, city_id)`. No table contract changes.
4. **Contract — extra columns added (allowed: own tables).** `dim_date.is_publishing_day`; `dim_province.pihps_province_id`, `production_center_commodities`; `dim_city.has_<tier>`; `dim_commodity.is_v1`; `stg_pihps_price.is_jump_flag`, `request_key`.
5. **Spec — data publishes weekdays only.** `fct_daily_price` has no weekend or holiday rows. DS lag features (t−1, t−7 …) and the D4 backtest ("buy each day") need to decide calendar vs published days. Suggest calendar days with as-of lookups, as `fct_price_change` does.
6. **Spec — `stg_weather_forecast` (S5) cannot be trained on.** BMKG keeps no forecast history, so any model feature built from it exists only in production (train/serve skew). Suggest dropping S5 from model features, or archiving forecasts from now and using them only after ~1 year.
7. **Spec — forecast gate baseline.** MASE vs seasonal-naive is an easy bar for 7–14-day food prices; the plain naive forecast is usually harder to beat. Suggest Gate 3 also require beating naive.
8. ~~**Spec — publishing the DuckDB file by daily git commit** will bloat the repo.~~ **Decided 2026-10-25:** publish to the `data` GitHub Release instead (see #9).
9. ~~**Decision — where the daily job runs.**~~ **Decided 2026-10-25:** GitHub-hosted runner (geo-probe passed) + GitHub Release assets for storage. `daily.yml` and `weekly_retrain.yml` are written; the schedule waits for #11.
10. **Owner action — verify the fuel seed.** `dbt/seeds/fuel_price_events.csv` has the 2022 changes only, from memory (`verified=false`). Add any later Pertalite/Solar changes.
11. **Owner action — switch the daily job on (once the local backfill finishes).** One-time:
    1. Install the GitHub CLI and log in: `winget install GitHub.cli`, then `gh auth login`.
    2. From the repo root: `.venv\Scripts\python -m ingestion.archive pack --out out --all` and `.venv\Scripts\python -m ingestion.archive pack-db --out out`.
    3. `gh release create data out/* --title "Pipeline data" --notes "Raw archives and the published database."`
    4. GitHub → Settings → Secrets and variables → Actions → **Variables** → new variable `PIPELINE_ENABLED` = `true`.
    5. Actions → **daily** → Run workflow once to check it end to end.
12. **Spec — public vs private repo.** The repo is private. Release assets of a private repo need a token to download, so the Streamlit dashboard would need a GitHub token secret. Making the repo public (as the spec intends) removes that, and makes Actions minutes unlimited.
10. **Owner action — verify the fuel seed.** `dbt/seeds/fuel_price_events.csv` has the 2022 changes only, from memory (`verified=false`). Add any later Pertalite/Solar changes.

## Data Analyst

## Data Scientist
