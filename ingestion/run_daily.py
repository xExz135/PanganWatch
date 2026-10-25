"""Daily incremental ingestion (TEAM.md entry point 1).

Re-fetches the last N days (config `daily.rolling_window_days`) for every city x tier,
because PIHPS may revise recent values; silver keeps the latest version per key.
Idempotent per --date: re-running the same date skips requests already done.

    python -m ingestion.run_daily [--date YYYY-MM-DD]

Exits non-zero if more than `max_failed_share` of requests failed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from ingestion.backfill import load_cities
from ingestion.config import sources
from ingestion.http import PoliteClient
from ingestion.manifest import Manifest
from ingestion.pihps import fetch_and_store, today_wib

log = logging.getLogger(__name__)


def main() -> int:
    cfg = sources()["pihps"]
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=date.fromisoformat, default=today_wib())
    p.add_argument("--tier", action="append")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    window = cfg["daily"]["rolling_window_days"]
    date_to = args.date
    date_from = date_to - timedelta(days=window)
    tiers = args.tier or cfg["backfill"]["tier_order"]

    manifest = Manifest("pihps")
    jobs = [
        (tier, int(c["city_id"]))
        for tier in tiers
        for c in load_cities()
        if c[f"has_{tier}"] == "True"
    ]
    log.info("daily run for %s: %s requests (%s..%s)", date_to, len(jobs), date_from, date_to)

    done = failed = 0
    with PoliteClient() as client:
        for tier, city_id in jobs:
            row = fetch_and_store(
                client, manifest,
                request_key=f"daily|{date_to}|{tier}|{city_id}",
                kind="daily", date_from=date_from, date_to=date_to,
                market_tier=tier, city_id=city_id,
            )
            if row is None:
                continue
            done += 1
            failed += row["status"] == "failed"

    log.info("done: %s fetched, %s failed", done, failed)
    if done and failed / done > cfg["daily"]["max_failed_share"]:
        log.error("too many failures (%s/%s)", failed, done)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
