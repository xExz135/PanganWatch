"""Historical daily weather per province (S4), from the Open-Meteo archive API.

One point per province (the capital's coordinates in dbt/seeds/provinces.csv).
Backfill = one request per province for the whole history; daily = the last N days
again (recent values are preliminary and get revised). Silver keeps the latest fetch.

    python -m ingestion.weather backfill
    python -m ingestion.weather daily [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date, timedelta

from ingestion.config import SEEDS_DIR, sources
from ingestion.http import PoliteClient
from ingestion.manifest import Manifest
from ingestion.pihps import today_wib
from ingestion.store import fetch_to_bronze, json_object

log = logging.getLogger(__name__)


def cfg() -> dict:
    return sources()["weather"]


def provinces() -> list[dict]:
    with (SEEDS_DIR / "provinces.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def validate_shape(body: bytes) -> tuple[str, int, str | None]:
    doc = json_object(body)
    if doc is None:
        return "failed", 0, "not a JSON object"
    if doc.get("error"):
        return "failed", 0, str(doc.get("reason"))[:200]
    daily = doc.get("daily")
    if not isinstance(daily, dict) or "time" not in daily:
        return "failed", 0, "missing daily.time"
    missing = [v for v in cfg()["daily_variables"] if v not in daily]
    if missing:
        return "failed", 0, f"missing variables {missing}"
    return ("ok" if daily["time"] else "empty"), len(daily["time"]), None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["backfill", "daily"])
    p.add_argument("--date", type=date.fromisoformat, default=today_wib())
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    end = args.date - timedelta(days=1)
    if args.mode == "backfill":
        start = date.fromisoformat(cfg()["history_start"])
    else:
        start = args.date - timedelta(days=cfg()["daily_window_days"])

    manifest = Manifest("weather")
    rows = []
    with PoliteClient() as client:
        for prov in provinces():
            pid = prov["province_id"]
            key = (f"weather|backfill|{pid}" if args.mode == "backfill"
                   else f"weather|daily|{args.date}|{pid}")
            rows.append(fetch_to_bronze(
                client, manifest, source="weather", request_key=key, kind=args.mode,
                url=cfg()["base_url"],
                query={
                    "latitude": prov["lat"], "longitude": prov["lon"],
                    "start_date": start.isoformat(), "end_date": end.isoformat(),
                    "daily": ",".join(cfg()["daily_variables"]), "timezone": cfg()["timezone"],
                },
                params={"province_id": int(pid), "lat": float(prov["lat"]),
                        "lon": float(prov["lon"]), "start_date": start.isoformat(),
                        "end_date": end.isoformat()},
                file_stem=f"p{pid}_{start:%Y%m%d}_{end:%Y%m%d}", validate=validate_shape,
            ))
    failed = sum(1 for r in rows if r and r["status"] == "failed")
    log.info("weather %s done: %s fetched, %s failed", args.mode, sum(1 for r in rows if r), failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
