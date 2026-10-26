"""Weekly Python analyses (TEAM.md §3.3): write the ana_* tables that need statistics beyond SQL.

    python -m analytics.run [--date YYYY-MM-DD] [--db PATH]

Uses prices dated before --date (default: today WIB) and replaces its own tables, so a re-run
for the same date gives the same result. Needs the `analytics` extra (statsmodels).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from analytics import transmission

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
WIB = timezone(timedelta(hours=7))


def write_table(con, name: str, df) -> None:
    con.register("new_rows", df)
    try:
        con.execute(f"create or replace table {name} as select * from new_rows")
    finally:
        con.unregister("new_rows")


def main(argv: list[str] | None = None) -> int:
    import duckdb

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", type=date.fromisoformat, default=datetime.now(WIB).date())
    ap.add_argument("--db", default=os.environ.get("PANGANWATCH_DB",
                                                   str(ROOT / "data" / "panganwatch.duckdb")))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    con = duckdb.connect(args.db)
    try:
        lags, summary = transmission.run(con, before=args.date)
        if summary.empty:
            log.warning("A2: not enough matched producer and retail months; tables not written")
            return 0
        computed_at = datetime.now(UTC).replace(tzinfo=None)
        write_table(con, "ana_a2_transmission_lags", lags.assign(computed_at=computed_at))
        write_table(con, "ana_a2_transmission_summary",
                    summary.assign(data_before=args.date, computed_at=computed_at))
        log.info("A2: %s commodities, %s asymmetric at p < %s", len(summary),
                 int(summary["is_asymmetric"].sum()), transmission.ASYMMETRY_P)
    except Exception:
        log.exception("analytics run failed")
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
