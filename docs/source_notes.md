# Source notes

What each source returns and how to call it. Found by reading the page source; checked against the live site on 2026-10-25 from an Indonesian IP.

## S1 — PIHPS Nasional (Bank Indonesia)

- **Site:** https://www.bi.go.id/hargapangan (moved from hargapangan.id in 2023; old tutorials don't work).
- **Tech:** DevExtreme grids backed by ASP.NET JSON endpoints. Plain GET, no auth, no cookies, no CSRF token needed.
- **Base:** `https://www.bi.go.id/hargapangan/WebSite/TabelHarga/`

### Price table: `GetGridDataDaerah`

| Param | Meaning | Values |
|---|---|---|
| `price_type_id` | Market tier | 1 Pasar Tradisional, 2 Pasar Modern, 3 Pedagang Besar (wholesale), 4 Produsen (producer) |
| `comcat_id` | Commodity filter | `""` = all; `cat_N` = category; `com_N` = commodity; comma list allowed |
| `province_id` | Province filter | `""` = national; PIHPS province ids (not BPS codes); see `dbt/seeds/provinces.csv` |
| `regency_id` | City filter | `""` = all; PIHPS regency id |
| `market_id` | Market filter | `""` = all |
| `tipe_laporan` | Report type | 1 daily, 4 weekly, 5 monthly, 6 chart |
| `start_date`, `end_date` | Range | `yyyy-MM-dd` |

Response:

```json
{"data":[
  {"no":"I","name":"Cabai Rawit","level":1,"13/10/2026":"74,850", ...},
  {"no":1,"name":"Cabai Rawit Hijau","level":2,"13/10/2026":"60,300", ...}
]}
```

- **Wide format:** one key per date (`dd/mm/yyyy`), price as text with comma thousands separators.
- `level: 1` rows are category averages; `level: 2` rows are commodities. Silver keeps level 2 only.
- Rows carry the commodity **name**, not its id. Silver maps names via `dbt/seeds/pihps_commodity_names.csv`. One name has a trailing space (`"Cabai Merah Keriting "`), so names are trimmed.

### Things that shape the whole pipeline

1. **Weekdays only.** No weekend columns (e.g. 17–18 Oct 2026 absent). Holidays are *not* always skipped: 1 Jan 2026 has prices. `dim_date.is_publishing_day` (weekday and not a holiday) is therefore a conservative guess; the freshness test counts these days, so an extra published holiday can only make it more lenient, never fail it.
2. **Multi-select is averaged.** Selecting several provinces or cities returns *one* blended row, not one per area. Per-city data therefore needs **one request per city**. The spec's `fetch(..., province_code)` became `fetch(..., city_id)`.
3. **Long ranges work.** One city × one tier × one full year = ~260 date columns in ~40 s. Backfill uses calendar-year chunks: ~406 city-tier pairs × 5 years ≈ 2,000 requests ≈ a day at 2 s spacing.
4. **All tiers list all 21 commodities**, rice included at producer tier (no gabah conversion needed). Producer tier has the *most* cities (143), **but each producer city reports only some commodities**: Kota Surabaya's producer tier has 5 (beef and oil only) in 2026. Province-level farm-to-retail margins depend on pooling cities; check producer coverage per commodity × province before A1/A2.
5. **34 provinces** (pre-2022 structure; the new Papua provinces are not split out).
6. **Units:** the `denomination` field says `kg` for every commodity, including cooking oil; supply data for oil is in kilolitres, so oil prices are treated as **per liter**. *To verify on the rendered page.*

### Reference lists

| Endpoint | Params | Returns |
|---|---|---|
| `GetRefPriceType` | – | the 4 tiers |
| `GetRefCommodityAndCategory` | – | 10 categories (`cat_N`) + 21 commodities (`com_N`) |
| `GetRefProvince` | – | 34 provinces |
| `GetRefRegency` | `ref_prov_id`, `price_type_id` | cities reporting in that province × tier |

Cities per tier (2026-10-25): traditional 110, modern 78, wholesale 75, producer 143. Regenerate with `python -m ingestion.refs`.

### Access

- Reachable from Indonesia without blocks. **Geo-block test from GitHub Actions (US) still to do** (Week 1 task).
- Politeness: 2 s between requests, User-Agent with contact email, 3 retries (2/8/30 s) on timeouts and 5xx.

## S2–S10

Not started. BPS (S3) needs an API key from webapi.bps.go.id (owner action).
