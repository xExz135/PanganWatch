# Decisions

One line per decision and why. Each role edits only its own section (TEAM.md §2).

## Data Engineer

- **2026-10-25 — Geo-block test passed: PIHPS answers GitHub-hosted (US) runners.** No laptop/VPS fallback needed for ingestion.
- **2026-10-25 — Scrape per city, not per province.** PIHPS averages multi-area selections into one row, so per-city requests are the only way to compute our own province median (spec §6).
- **2026-10-25 — Backfill in calendar-year chunks, not months.** One year per request works (~40 s); 12× fewer requests than monthly chunks for the same data.
- **2026-10-25 — Bronze = raw files + append-only `_manifest.jsonl`, not a DuckDB table.** DuckDB allows one writer; a multi-day backfill writing to the DB would block `dbt build`. dbt reads the files directly (`bronze_pihps_raw` view), so bronze stays queryable and untouched.
- **2026-10-25 — Keep all 21 PIHPS commodities in bronze and silver.** Every request returns all of them at no extra cost; `is_v1` marks the spec's 8. Avoids re-scraping when rice premium, beef and sugar are added.
- **2026-10-25 — `province_id` = BPS province code.** Standard code that BPS CPI and weather sources also use; PIHPS's own id kept as `pihps_province_id`.
- **2026-10-25 — v1 rice = "Beras Kualitas Medium I", v1 oil = "Minyak Goreng Curah".** Spec says "beras (medium)" and "minyak goreng"; PIHPS has two medium grades and three oil types. Medium I is the reference grade; bulk oil moved most in the 2022 crisis and is what kitchens buy in volume.
- **2026-10-25 — Calendar-day look-backs for 7d/28d changes.** PIHPS skips weekends and holidays, so "7 days ago" means the latest price on or before date−7, NULL if stale.
- **2026-10-25 — Freshness test counts publishing days, not calendar days.** A calendar-day rule would fail every long weekend and the whole Lebaran break.
- **2026-10-25 — dbt generic tests written in-house instead of dbt-expectations.** Six small tests in `dbt/tests/generic/`; avoids a package download in CI for little gain.
- **2026-10-25 — pip + venv for now, not uv/Poetry.** uv isn't installed on the dev machine; `pyproject.toml` works with either.
- **2026-10-25 — CPI at three levels (national, province, city), food groups only.** National gives one unbroken 2021→now series across the 2024 base change; province matches the modelling grain; city is kept because it comes in the same requests.
- **2026-10-25 — Weather from Open-Meteo, not BMKG.** One free request returns 10+ years per province; BMKG's climate data needs an account and per-station work. One point per province (the capital) is a known simplification.
- **2026-10-25 — Weather history from 2015.** Rain anomalies need a "normal" to compare against; 10 years is enough.
- **2026-10-25 — USD/IDR from ECB via Frankfurter.** Official reference rate, free JSON API; JISDOR has no API and yfinance is unofficial.
- **2026-10-25 — Secrets never in URLs that get logged.** httpx's INFO URL logging is off; errors and manifests are redacted; tested.
- **2026-10-25 — `fct_pipeline_runs` / `fct_test_results` written by Python after `dbt build`, not by dbt.** A failed build must still be logged, and dbt can't log its own failure.
- **2026-10-25 — Daily job on GitHub-hosted runners, data kept in the `data` Release (owner decision).** Each run restores, runs, uploads. Raw data is stored as one archive per fetch month, so a run re-uploads only the current month. Raw archives are saved even when a run fails; the database is published only when every error-level test passes. Free, and git history stays small. Not MotherDuck: no extra account. Not the laptop: it would have to be on daily.
- **2026-10-25 — Run log kept as JSONL beside bronze, tables rebuilt from it.** A failed run never publishes the database, so a log stored only in the DB would lose failures; the JSONL travels with the raw archives.
- **2026-10-25 — Schedule off until `PIPELINE_ENABLED=true`.** If the scheduled job ran before the local backfill was uploaded, it would publish a month archive that the backfill upload would then overwrite.
- **2026-10-25 — Architecture diagram as Mermaid in the README, not `docs/architecture.png`.** GitHub renders it, it is diffable and can't drift from a binary copy. A PNG can be exported from it for the write-up if needed.
- **2026-10-25 — Missing sources give empty bronze views, not errors.** A fresh checkout without a BPS key still builds; tested.
- **2026-10-25 — Staging rebuilds fully from bronze each run (for now).** Simple and always correct; fine at today's ~2,000 files. Switch `stg_pihps_price` to incremental when the build passes ~5 minutes.

## Data Analyst

## Data Scientist
