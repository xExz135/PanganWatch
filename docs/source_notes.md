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

- Reachable from Indonesia without blocks, and **from GitHub Actions (US runners): geo-probe passed on 2026-10-25** (HTTP 200, ~8 s).
- Politeness: 2 s between requests, User-Agent with contact email, 3 retries (2/8/30 s) on timeouts and 5xx.

### Data quality seen in the first loads

- Single-city typos exist and are caught as warnings: e.g. premium rice in one city 11,900 → 34,400 → 11,900 on consecutive days; beef at Rp 455,000/kg. The province median absorbs them.
- **2022 cooking-oil crisis shows up as out-of-bounds prices:** branded oil (`minyak_goreng_kemasan_1`) in Kota Kendari and Kota Bau-Bau (Sulawesi Tenggara) went from ~Rp 22,000 to Rp 55,000–57,000 in Mar 2022 and eased back to ~Rp 24,000 by Oct 2022 (Kota Parepare: one day at 88,250). The gradual path looks real, but some reports may be 2-liter pack prices. Kept as reported (warn only); not a v1 commodity. Analyses of branded oil in 2022 should check these cities.

## S3 — BPS WebAPI (CPI)

- **Endpoint:** `https://webapi.bps.go.id/v1/api/list/model/data/lang/eng/domain/0000/var/<var_id>/th/<year-1900>/key/<KEY>/`. The key is in the URL path, so httpx's URL logging is switched off and errors are redacted.
- **`th` is required** (year − 1900, e.g. 125 = 2025). One request = one table × one year.
- **Rate limit ≈ 20 requests/minute** → HTTP 429 with `{"retry_after": 60}`. We sleep 4 s and honour `retry_after`.
- **Values are packed under one key**: `region || table || group || year || month`, e.g. `1` `2212` `1551` `125` `1` → `"1221215511251"`. Month 13 = annual. `stg_cpi` splits at `table||group` and validates the region against the table's own list.
- **The CPI base changed in 2024**, and each base has different table ids:

  | Base | Index | m-o-m | y-o-y | Regions |
  |---|---|---|---|---|
  | 2018=100 (≤ 2023) | 1905 | 1890 | — (derived from index) | 90 cities, region = BPS code (e.g. 1171) |
  | 2022=100 (≥ 2024) | 2212 | 2223 | 2250 | 150 cities, region = row number 1–151 (no code) |
  | 2022=100, provinces | 2305 | 2293 | — | 38 provinces, region = BPS code (1100 …) |

  `INDONESIA` (9999 or 151) is the national row. Index values are only comparable within one base; m-o-m and y-o-y are comparable across.
- **Groups kept:** 1551 food, beverages & tobacco; 1552 food.
- **City mapping:** 95 of 150 BPS cities match a PIHPS city by name. 2022-base cities have no code, so their province comes from that match (NULL if unmatched).
- **38 vs 34 provinces:** BPS has the 2022 Papua split; PIHPS doesn't. The four new provinces get `province_id` NULL.

## S4 — Weather history (Open-Meteo archive)

- `https://archive-api.open-meteo.com/v1/archive`, no key, free for non-commercial use, **CC BY 4.0: credit "Weather data by Open-Meteo.com"**.
- One point per province (capital coordinates in `provinces.csv`). Variables: `precipitation_sum`, `temperature_2m_mean`, `temperature_2m_max`, timezone Asia/Jakarta.
- Full 2015→yesterday history in one request per province (~6 s). Daily run re-fetches the last 14 days (recent days are preliminary).
- Seen once: the server cut a long response mid-stream ("Unexpected error while streaming data: timeoutReached"), returned with HTTP 200. The shape check marked it failed; a re-run fixed it.

## S7 — USD/IDR (Frankfurter / ECB)

- `https://api.frankfurter.dev/v1/<start>..<end>?from=USD&to=IDR`, no key. ECB euro reference rates cross-rated to USD/IDR; published on TARGET working days only. `stg_fx` forward-fills gaps with `is_filled = true`.
- Chosen over JISDOR (form download, no API) and yfinance (unofficial, extra dependency).

## S8 — Fuel price events

- Hand-built seed `dbt/seeds/fuel_price_events.csv`, one row per price change with a source. Unverified; covers 2022 changes only.

## S2, S5, S9, S10

Not started. S5 (BMKG forecast) is on hold: see owner_requests.md item 6.
