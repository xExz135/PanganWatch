"""One-time history backfill: every city x tier x calendar year since the start date.

Resumable: anything already in the manifest is skipped, so stop and restart freely.

    python -m ingestion.backfill                       # everything, config order
    python -m ingestion.backfill --tier traditional --year 2026
    python -m ingestion.backfill --city 34 --limit 5   # quick test
"""

from __future__ import annotations

import argparse
import csv
import logging
from datetime import date, timedelta

from ingestion.config import SEEDS_DIR, sources
from ingestion.http import PoliteClient
from ingestion.manifest import Manifest
from ingestion.pihps import fetch_and_store, today_wib

log = logging.getLogger(__name__)


def load_cities() -> list[dict]:
    with (SEEDS_DIR / "pihps_cities.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def plan(tiers: list[str], years: list[int], cities: list[dict], end: date) -> list[dict]:
    jobs = []
    for tier in tiers:
        for year in years:
            for c in cities:
                if c[f"has_{tier}"] != "True":
                    continue
                start = date(year, 1, 1)
                stop = min(date(year, 12, 31), end)
                if start > stop:
                    continue
                jobs.append({
                    "request_key": f"backfill|{tier}|{c['city_id']}|{year}",
                    "market_tier": tier,
                    "city_id": int(c["city_id"]),
                    "date_from": start,
                    "date_to": stop,
                })
    return jobs


def main() -> None:
    cfg = sources()["pihps"]
    p = argparse.ArgumentParser()
    p.add_argument("--tier", action="append", help="repeatable; default: all, config order")
    p.add_argument("--year", type=int, action="append", help="repeatable; default: start..now")
    p.add_argument("--city", type=int, action="append")
    p.add_argument("--limit", type=int, help="stop after N fetches (testing)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # History ends the day before the daily run's rolling window starts.
    end = today_wib() - timedelta(days=cfg["daily"]["rolling_window_days"] + 1)
    first_year = date.fromisoformat(cfg["backfill"]["start_date"]).year
    years = args.year or list(range(first_year, end.year + 1))
    tiers = args.tier or cfg["backfill"]["tier_order"]
    cities = [c for c in load_cities() if not args.city or int(c["city_id"]) in args.city]

    manifest = Manifest("pihps")
    jobs = [j for j in plan(tiers, years, cities, end) if not manifest.has_ok(j["request_key"])]
    if args.limit:
        jobs = jobs[: args.limit]
    log.info("%s requests to go", len(jobs))

    failed = 0
    with PoliteClient() as client:
        for i, job in enumerate(jobs, 1):
            row = fetch_and_store(client, manifest, kind="backfill", **job)
            if row and row["status"] == "failed":
                failed += 1
            if row:
                log.info("[%s/%s] %s -> %s (%s rows)", i, len(jobs), job["request_key"],
                         row["status"], row["n_rows"])
    log.info("backfill pass done: %s requests, %s failed (re-run to retry)", len(jobs), failed)


if __name__ == "__main__":
    main()
