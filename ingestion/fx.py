"""USD/IDR daily exchange rate (S7), ECB reference rates via the Frankfurter API.

ECB publishes on TARGET working days only; stg_fx forward-fills the gaps and flags them.
Backfill = one request for the whole history; daily = the last N days again.

    python -m ingestion.fx backfill
    python -m ingestion.fx daily [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from ingestion.config import sources
from ingestion.http import PoliteClient
from ingestion.manifest import Manifest
from ingestion.pihps import today_wib
from ingestion.store import fetch_to_bronze, json_object

log = logging.getLogger(__name__)


def cfg() -> dict:
    return sources()["fx"]


def validate_shape(body: bytes) -> tuple[str, int, str | None]:
    doc = json_object(body)
    if doc is None:
        return "failed", 0, "not a JSON object"
    rates = doc.get("rates")
    if not isinstance(rates, dict):
        return "failed", 0, f"missing rates: {str(doc.get('message'))[:200]}"
    if any(cfg()["quote"] not in v for v in rates.values()):
        return "failed", 0, f"a day without {cfg()['quote']}"
    return ("ok" if rates else "empty"), len(rates), None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["backfill", "daily"])
    p.add_argument("--date", type=date.fromisoformat, default=today_wib())
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    end = args.date
    start = (date.fromisoformat(cfg()["history_start"]) if args.mode == "backfill"
             else end - timedelta(days=cfg()["daily_window_days"]))
    key = "fx|backfill" if args.mode == "backfill" else f"fx|daily|{args.date}"
    with PoliteClient() as client:
        row = fetch_to_bronze(
            client, Manifest("fx"), source="fx", request_key=key, kind=args.mode,
            url=f"{cfg()['base_url']}/{start.isoformat()}..{end.isoformat()}",
            query={"from": cfg()["base"], "to": cfg()["quote"]},
            params={"base": cfg()["base"], "quote": cfg()["quote"],
                    "start_date": start.isoformat(), "end_date": end.isoformat()},
            file_stem=f"{cfg()['base'].lower()}{cfg()['quote'].lower()}_{start:%Y%m%d}_{end:%Y%m%d}",
            validate=validate_shape,
        )
    return 1 if row and row["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
