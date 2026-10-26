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

## Data Analyst

1. **Dependency — dashboard.** Add `streamlit` and `plotly` (spec §5 tech stack) for `dashboard/`. **Approved by owner 2026-10-25; added by DE** as the optional group `.[dashboard]` so the daily pipeline doesn't install them. Streamlit Community Cloud installs from `dashboard/requirements.txt`.
2. **Owner check — reference prices taken from news reports.** `dbt/seeds/reference_prices.csv` cites the official text for most rows. Four sources had no official copy online, so their values were checked against news reports (`source_kind = press_report`): Permendag 57/2017 (rice before Mar 2023), Permendag 7/2020 (eggs and chicken before Oct 2022), the 2024 rice relaxation letters, and Kepbadan 299/2025 (current rice ceiling). If you can get the official PDFs, send them and I will swap the links. Also: in Feb 2026 the Ombudsman asked Bapanas to revoke Kepbadan 299/2025; I found no sign it was revoked, so the seed treats it as still in force.
3. **Contract — extra columns (own tables).** `dim_reference_price`: `zone`, `price_idr_low` (lower end of a HAP range), `unit`, `regulation`, `source_kind`, `note`, `overlaps_other_period`. `fct_reference_compliance`: `market_tier` (traditional and modern, both retail), `price_type`, `regulation`. No other role's tables change.

## Data Scientist

1. **Spec — the MASE gate (Gate 3) is measured against the wrong yardstick at 14 days.** MASE divides by the typical 7-day price change in the training data, so longer horizons are judged against a shorter-range bar. On the local data (partial history; 13 folds up to 2026-10-16, `python -m ml.backtest`), the plain copy-yesterday forecast already scores MASE 0.79 at 7 days and 1.28 at 14 days; seasonal naive scores 1.19 and 1.63. Seasonal naive is also easy to beat: naive's MAE is 0.74× seasonal naive's at 7 days and 0.84× at 14 days (supports DE item 7). Suggestion: keep reporting MASE, but define the gate as "MAE below seasonal naive **and** below naive at the same horizon". Recording those ratios in `fct_model_metrics` needs a new `metric` value (e.g. `mae_vs_snaive`), which is a contract change, so I need your approval. **Approved by owner 2026-10-25:** Gate 3 = beats naive at 7 and 14 days (`relmae_naive` < 1 and `share_series_beating_naive` > 0.5), coverage 75–85%; MASE stays reported. New metric values `relmae_naive`, `relmae_snaive`, `share_series_beating_naive` added to the `fct_model_metrics` contract (TEAM.md §3.2) and to `ml.backtest`.
2. **Dependencies — Weeks 7–10 need:** `lightgbm`, `mlforecast`, `statsforecast` (AutoETS baseline), `shap`, `scikit-learn` (calibration). Suggest DE adds them as an optional group `.[ml]` so the daily ingest job stays light. **Approved by owner 2026-10-25;** DE adds them when Week 7 work starts.
3. **Contract — extra columns (own tables).** `fct_forecast`: `created_at` (UTC), so the ledger integrity test can prove no forecast was written after its `run_date`. `fct_forecast_ledger`: the forecast's keys (`run_date`, `target_date`, `horizon_days`, `commodity_id`, `province_id`, `model_version`) next to the spec's `actual_price`, `abs_error`, `pct_error`, `in_interval_80`, `scored_at`. `pct_error` = `abs_error` / actual (unsigned decimal). No other role's tables change.
