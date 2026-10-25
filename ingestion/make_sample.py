"""Build data/sample/panganwatch_sample.duckdb from the full DB (TEAM.md §3.5).

Every DE contract table, cut to a few provinces and commodities, with enough history
(>= 400 days) for year-ago lags. DA and DS develop on local copies of this file.

    python -m ingestion.make_sample
"""

from __future__ import annotations

import logging

import duckdb

from ingestion.config import DATA_DIR

log = logging.getLogger(__name__)

PROVINCES = [31, 35, 12]  # DKI Jakarta, Jawa Timur, Sumatera Utara
COMMODITIES = ["cabai_rawit_merah", "bawang_merah", "beras_medium_1"]
MIN_DAYS = 400

# table -> filter (None = copy whole table)
TABLES: dict[str, str | None] = {
    "dim_date": None,
    "dim_commodity": None,
    "dim_province": None,
    "dim_city": None,
    "dim_market_tier": None,
    "stg_pihps_price": "province_id in {p} and commodity_id in {c}",
    "fct_daily_price": "province_id in {p} and commodity_id in {c}",
    "fct_price_change": "province_id in {p} and commodity_id in {c}",
    "fct_margin_chain": "province_id in {p} and commodity_id in {c}",
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    src = DATA_DIR / "panganwatch.duckdb"
    out = DATA_DIR / "sample" / "panganwatch_sample.duckdb"
    out.unlink(missing_ok=True)

    con = duckdb.connect(str(out))
    con.execute(f"attach '{src.as_posix()}' as full (read_only)")
    p = "(" + ", ".join(str(x) for x in PROVINCES) + ")"
    c = "(" + ", ".join(f"'{x}'" for x in COMMODITIES) + ")"
    for table, where in TABLES.items():
        clause = f" where {where.format(p=p, c=c)}" if where else ""
        con.execute(f"create table main.{table} as select * from full.main.{table}{clause}")
        n = con.execute(f"select count(*) from main.{table}").fetchone()[0]
        log.info("%-20s %8s rows", table, n)

    span = con.execute("select max(date) - min(date) from fct_daily_price").fetchone()[0]
    if span is None or span < MIN_DAYS:
        raise SystemExit(f"sample covers {span} days; need >= {MIN_DAYS}. Backfill more first.")
    con.execute("detach full")
    con.close()
    log.info("wrote %s (%s days of history)", out, span)


if __name__ == "__main__":
    main()
