"""BPS WebAPI: monthly consumer price indices (S3).

One request = one table (var_id) x one year. Completed years are fetched once;
the current year (and `refetch_recent_years` before it) are re-fetched each run,
because BPS adds a month at the start of every month. Silver keeps the latest fetch.

    python -m ingestion.bps [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from ingestion.config import secret, sources
from ingestion.http import PoliteClient
from ingestion.manifest import Manifest
from ingestion.pihps import today_wib
from ingestion.store import fetch_to_bronze, json_object

log = logging.getLogger(__name__)


def cfg() -> dict:
    return sources()["bps"]


def validate_shape(body: bytes) -> tuple[str, int, str | None]:
    """(status, n_values, error): ok | empty | failed."""
    doc = json_object(body)
    if doc is None:
        return "failed", 0, "not a JSON object"
    if doc.get("status") != "OK":
        return "failed", 0, f"API status {doc.get('status')}: {str(doc.get('message'))[:200]}"
    if doc.get("data-availability") != "available":
        return "empty", 0, None
    missing = [k for k in ("vervar", "turvar", "tahun", "turtahun", "datacontent") if k not in doc]
    if missing:
        return "failed", 0, f"missing keys {missing}"
    return "ok", len(doc["datacontent"]), None


def plan(as_of: date) -> list[dict]:
    jobs = []
    recent_from = as_of.year - cfg()["refetch_recent_years"]
    for t in cfg()["tables"]:
        first, last = t["years"]
        for year in range(first, (last or as_of.year) + 1):
            # Recent years get a per-day key so they are re-fetched; old ones are final.
            key = f"bps|{t['var_id']}|{year}" + (f"|{as_of}" if year >= recent_from else "")
            jobs.append({
                "request_key": key, "var_id": t["var_id"], "year": year,
                "measure": t["measure"], "base_year": t["base_year"], "level": t["level"],
            })
    return jobs


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=date.fromisoformat, default=today_wib())
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    key = secret("BPS_API_KEY")
    manifest = Manifest("bps")
    rows = []
    with PoliteClient(sleep_seconds=cfg()["sleep_seconds"]) as client:
        for job in plan(args.date):
            th = job["year"] - cfg()["year_offset"]
            rows.append(fetch_to_bronze(
                client, manifest, source="bps", request_key=job["request_key"], kind="bps",
                url=f"{cfg()['base_url']}/var/{job['var_id']}/th/{th}/key/{key}/",
                # Never put the key in params: they are written to the manifest.
                params={**{k: v for k, v in job.items() if k != "request_key"}, "th": th},
                file_stem=f"var{job['var_id']}_y{job['year']}", validate=validate_shape,
            ))
    failed = sum(1 for r in rows if r and r["status"] == "failed")
    log.info("BPS done: %s fetched, %s failed", sum(1 for r in rows if r), failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
