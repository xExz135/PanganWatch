# Decisions

One line per decision and why. Each role edits only its own section (TEAM.md §2).

## Data Engineer

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

## Data Analyst

## Data Scientist
