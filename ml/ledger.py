"""Score published forecasts against real prices into fct_forecast_ledger (TEAM.md §3.3 step 3).

    python -m ml.ledger [--date YYYY-MM-DD] [--db PATH]

Scores every forecast whose target date is before --date, once its price is published and
not imputed. A target with no price (weekend, holiday, a city that didn't report) stays
unscored; a late price is picked up on a later run. A scored row is never rescored, even if
PIHPS later revises that price, so the ledger shows what was known when it was scored.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from ml.settings import settings
from ml.store import default_db, ensure_tables, today_wib, utc_now

log = logging.getLogger(__name__)

KEYS = ["run_date", "model_version", "commodity_id", "province_id", "horizon_days"]


def score(con, run_date: date) -> int:
    """Append newly scorable forecasts to the ledger. Returns rows written."""
    ensure_tables(con)
    tier = settings()["target"]["market_tier"]
    match = " and ".join(f"l.{k} = f.{k}" for k in KEYS)
    before = con.execute("select count(*) from fct_forecast_ledger").fetchone()[0]
    con.execute(f"""
        insert into fct_forecast_ledger
        select
            f.run_date, f.target_date, f.horizon_days, f.commodity_id, f.province_id,
            f.model_version,
            p.price_idr as actual_price,
            abs(f.q50 - p.price_idr) as abs_error,
            abs(f.q50 - p.price_idr) / p.price_idr::double as pct_error,
            p.price_idr between f.q10 and f.q90 as in_interval_80,
            ?::timestamp as scored_at
        from fct_forecast f
        join fct_daily_price p
          on p.date = f.target_date
         and p.commodity_id = f.commodity_id
         and p.province_id = f.province_id
         and p.market_tier = ?
         and not p.is_imputed
         and p.price_idr > 0
        where f.target_date < ?
          and not exists (select 1 from fct_forecast_ledger l where {match})
    """, [utc_now(), tier, run_date])
    written = con.execute("select count(*) from fct_forecast_ledger").fetchone()[0] - before
    log.info("scored %s forecasts with targets before %s", written, run_date)
    return written


def main(argv: list[str] | None = None) -> int:
    import duckdb

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", type=date.fromisoformat, default=today_wib())
    ap.add_argument("--db", default=default_db())
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    con = duckdb.connect(args.db)
    try:
        score(con, args.date)
    except Exception:
        log.exception("ledger for %s failed", args.date)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
