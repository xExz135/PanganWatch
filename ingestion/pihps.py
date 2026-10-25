"""PIHPS (Bank Indonesia) scraper.

One request = one city x one market tier x one date range, all 21 commodities.
Selecting several cities or provinces in one request makes PIHPS average them, so
per-city data needs one request per city (docs/source_notes.md).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ingestion.config import BRONZE_DIR, sources
from ingestion.http import PoliteClient
from ingestion.manifest import Manifest

log = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))
DATE_KEY = re.compile(r"^\d{2}/\d{2}/\d{4}$")
META_KEYS = {"no", "name", "level"}


def cfg() -> dict:
    return sources()["pihps"]


def today_wib() -> date:
    return datetime.now(WIB).date()


def tier_code(market_tier: str) -> int:
    return cfg()["market_tiers"][market_tier]


def grid_params(date_from: date, date_to: date, market_tier: str, city_id: int) -> dict:
    fmt = cfg()["date_format"]
    return {
        "price_type_id": tier_code(market_tier),
        "comcat_id": "",
        "province_id": "",
        "regency_id": str(city_id),
        "market_id": "",
        "tipe_laporan": cfg()["report_type_daily"],
        "start_date": date_from.strftime(fmt),
        "end_date": date_to.strftime(fmt),
    }


def validate_shape(body: bytes) -> tuple[str, int, str | None]:
    """Check a grid response at the door. Returns (status, n_rows, error).

    status is "ok" (rows present), "empty" (valid, no rows) or "failed" (shape changed).
    """
    try:
        doc = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return "failed", 0, f"not JSON: {e}"
    if not isinstance(doc, dict) or not isinstance(doc.get("data"), list):
        return "failed", 0, "missing top-level 'data' list"
    rows = doc["data"]
    if not rows:
        return "empty", 0, None
    for r in rows:
        if not isinstance(r, dict) or not {"name", "level"} <= r.keys():
            return "failed", 0, "row without 'name'/'level'"
        bad = [k for k in r if k not in META_KEYS and not DATE_KEY.match(k)]
        if bad:
            return "failed", 0, f"unexpected keys: {bad[:3]}"
    return "ok", len(rows), None


def fetch(
    client: PoliteClient, date_from: date, date_to: date, market_tier: str, city_id: int
) -> tuple[int, bytes, dict]:
    """Fetch one grid. Returns (http_status, raw body, request params)."""
    params = grid_params(date_from, date_to, market_tier, city_id)
    url = f"{cfg()['base_url']}/{cfg()['endpoints']['grid']}"
    r = client.get(url, params=params)
    return r.status, r.body, params


def bronze_path(market_tier: str, city_id: int, date_from: date, date_to: date) -> Path:
    fetched = today_wib().isoformat()
    name = f"{market_tier}_c{city_id}_{date_from:%Y%m%d}_{date_to:%Y%m%d}.json"
    return BRONZE_DIR / "pihps" / fetched / name


def save_bronze(body: bytes, path: Path) -> str:
    """Write the response exactly as received. Bronze files are never edited."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():  # same request twice in one day: keep the first, never overwrite
        path = path.with_name(f"{path.stem}_{datetime.now(WIB):%H%M%S}{path.suffix}")
    path.write_bytes(body)
    return path.relative_to(BRONZE_DIR).as_posix()  # relative to bronze root, e.g. pihps/…


def fetch_and_store(
    client: PoliteClient,
    manifest: Manifest,
    *,
    request_key: str,
    kind: str,
    date_from: date,
    date_to: date,
    market_tier: str,
    city_id: int,
) -> dict | None:
    """Fetch one grid unless already done; save to bronze; log a manifest row.

    Never raises for a single bad request: the failure is logged and the run goes on.
    """
    if manifest.has_ok(request_key):
        return None
    params = {
        **grid_params(date_from, date_to, market_tier, city_id),
        "market_tier": market_tier,
        "city_id": city_id,
    }
    try:
        http_status, body, _ = fetch(client, date_from, date_to, market_tier, city_id)
    except Exception as e:  # noqa: BLE001 - logged as a failure row, run continues
        log.error("fetch failed %s: %s", request_key, e)
        return manifest.record(
            request_key=request_key, kind=kind, params=params, status="failed",
            http_status=None, file_path=None, n_rows=None, error=str(e)[:500],
        )
    file_path = save_bronze(body, bronze_path(market_tier, city_id, date_from, date_to))
    if http_status != 200:
        status, n_rows, error = "failed", 0, f"HTTP {http_status}"
    else:
        status, n_rows, error = validate_shape(body)
    if status == "failed":
        log.error("bad response %s: %s", request_key, error)
    return manifest.record(
        request_key=request_key, kind=kind, params=params, status=status,
        http_status=http_status, file_path=file_path, n_rows=n_rows, error=error,
    )
