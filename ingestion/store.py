"""Shared fetch -> bronze -> manifest step for the small JSON sources (BPS, weather, FX)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime

from ingestion.config import BRONZE_DIR, redact
from ingestion.http import PoliteClient
from ingestion.manifest import Manifest
from ingestion.pihps import WIB, today_wib

log = logging.getLogger(__name__)

Validator = Callable[[bytes], tuple[str, int, str | None]]


def json_object(body: bytes) -> dict | None:
    try:
        doc = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def fetch_to_bronze(
    client: PoliteClient,
    manifest: Manifest,
    *,
    source: str,
    request_key: str,
    kind: str,
    url: str,
    params: dict,
    file_stem: str,
    validate: Validator,
    query: dict | None = None,
) -> dict | None:
    """Fetch url unless request_key is done; save the body as received; log a manifest row.

    `params` is what gets written to the manifest: never put secrets in it.
    Returns the manifest row, or None if skipped.
    """
    if manifest.has_ok(request_key):
        return None
    try:
        r = client.get(url, params=query)
    except Exception as e:  # noqa: BLE001 - logged as a failure row, run continues
        log.error("%s failed: %s", request_key, redact(str(e)))
        return manifest.record(request_key=request_key, kind=kind, params=params,
                               status="failed", http_status=None, file_path=None,
                               n_rows=None, error=redact(str(e))[:500])
    path = BRONZE_DIR / source / today_wib().isoformat() / (
        f"{file_stem}_{datetime.now(WIB):%H%M%S}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.body)
    if r.status != 200:
        status, n, error = "failed", 0, f"HTTP {r.status}"
    else:
        status, n, error = validate(r.body)
    row = manifest.record(request_key=request_key, kind=kind, params=params, status=status,
                          http_status=r.status, file_path=path.relative_to(BRONZE_DIR).as_posix(),
                          n_rows=n, error=error)
    log.info("%s -> %s (%s)", request_key, status, n)
    return row
