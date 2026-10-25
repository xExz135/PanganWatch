"""Append-only record of every fetch attempt, one JSON object per line.

Bronze is plain files plus this manifest (not a DuckDB table) so a multi-day backfill
never holds the database write lock that dbt needs. See docs/decisions.md.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ingestion.config import BRONZE_DIR

# An "empty" answer (valid shape, no rows) is final too: a city with no data that year.
DONE = {"ok", "empty"}


class Manifest:
    def __init__(self, source: str, root: Path = BRONZE_DIR) -> None:
        self.path = root / source / "_manifest.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ok_keys: set[str] | None = None

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def ok_keys(self) -> set[str]:
        if self._ok_keys is None:
            self._ok_keys = {r["request_key"] for r in self.rows() if r["status"] in DONE}
        return self._ok_keys

    def has_ok(self, request_key: str) -> bool:
        return request_key in self.ok_keys()

    def record(
        self,
        *,
        request_key: str,
        kind: str,
        params: dict,
        status: str,
        http_status: int | None,
        file_path: str | None,
        n_rows: int | None,
        error: str | None = None,
    ) -> dict:
        row = {
            "request_key": request_key,
            "kind": kind,
            "params": params,
            "status": status,  # ok | empty | failed
            "http_status": http_status,
            "file_path": file_path,
            "n_rows": n_rows,
            "error": error,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if status in DONE:
            self.ok_keys().add(request_key)
        return row
