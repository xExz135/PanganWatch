# PanganWatch

**PanganWatch tells a food buyer which prices are about to spike, where, and whether to buy now or wait — and shows how much that would have saved.**

> Status: Phase 1 (data platform) in progress. Headline numbers appear here once Gate 4 passes.

<!-- owner: data-engineer -->
## Data pipeline

Daily prices for 21 strategic commodities from Bank Indonesia's **PIHPS** across all four market tiers (producer, wholesale, traditional, modern), 171 cities in 34 provinces, from 2022 onward.

```
PIHPS (per city × tier) ──► bronze: raw JSON files + fetch manifest (never edited)
                         ──► silver: stg_pihps_price (dbt, tested)
                         ──► gold:   dim_* + fct_daily_price, fct_price_change, fct_margin_chain
```

- **Idempotent:** every fetch is recorded in a manifest; re-runs skip what is done.
- **Polite:** 2 s between requests, descriptive User-Agent, retries only on timeouts/5xx.
- **Gated:** `dbt build` runs models and tests together; an error-level failure stops the publish.

### Run locally

```bash
python -m venv .venv && .venv/Scripts/pip install -e .[dev]   # macOS/Linux: .venv/bin/pip
python -m ingestion.backfill --year 2026 --tier traditional --city 34   # small slice
cd dbt && dbt build --profiles-dir .
pytest
```

### Data sources and credits

- **PIHPS Nasional — Bank Indonesia**, https://www.bi.go.id/hargapangan. Data © Bank Indonesia; used for non-commercial research with attribution. Raw dumps are not redistributed.
<!-- /owner: data-engineer -->
