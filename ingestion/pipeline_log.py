"""Record a pipeline run and its dbt test results (fct_pipeline_runs, fct_test_results).

Runs after `dbt build` (pass or fail) and reads dbt/target/run_results.json + manifest.json.
Both tables are append-only and written here, not by dbt, so a failed build still logs.

    python -m ingestion.pipeline_log --run-id 123 --started-at 2026-10-25T07:00:00+00:00 \
        --status success [--notes "..."]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from ingestion.config import BRONZE_DIR, DATA_DIR, ROOT

log = logging.getLogger(__name__)

TARGET = ROOT / "dbt" / "target"
LAYER_BY_FOLDER = {"staging": "silver", "marts": "gold", "ml": "ml", "analyses": "analyses"}

DDL = """
create table if not exists fct_pipeline_runs (
    run_id varchar primary key, started_at timestamptz, finished_at timestamptz,
    status varchar, rows_loaded bigint, requests_failed bigint, tests_failed integer,
    tests_warned integer, notes varchar
);
create table if not exists fct_test_results (
    run_id varchar, run_at timestamptz, test_name varchar, model_name varchar,
    layer varchar, severity varchar, status varchar, failures bigint
);
"""


def test_rows(run_id: str, target: Path = TARGET) -> list[dict]:
    """One row per dbt test in the last build, mapped to its model and layer."""
    results_path = target / "run_results.json"
    if not results_path.exists():
        return []
    results = json.loads(results_path.read_text(encoding="utf-8"))
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    nodes = manifest["nodes"]
    run_at = results["metadata"]["generated_at"]
    rows = []
    for r in results["results"]:
        uid = r["unique_id"]
        if not uid.startswith("test."):
            continue
        node = nodes.get(uid, {})
        parent_id = node.get("attached_node") or next(
            (d for d in node.get("depends_on", {}).get("nodes", []) if d.startswith("model.")),
            None,
        )
        parent = nodes.get(parent_id or "", {})
        folder = Path(parent.get("original_file_path", "")).parts
        layer = next((LAYER_BY_FOLDER[p] for p in folder if p in LAYER_BY_FOLDER), "other")
        status = {"pass": "pass", "warn": "warn"}.get(r["status"], "fail")
        rows.append({
            "run_id": run_id, "run_at": run_at, "test_name": node.get("name", uid),
            "model_name": parent.get("name"), "layer": layer,
            "severity": (node.get("config", {}).get("severity") or "error").lower(),
            "status": status, "failures": r.get("failures") or 0,
        })
    return rows


def rows_loaded_since(started_at: datetime) -> tuple[int, int]:
    """(rows fetched OK, requests failed) across all source manifests since started_at."""
    ok_rows = failed = 0
    for path in BRONZE_DIR.glob("*/_manifest.jsonl"):
        with path.open(encoding="utf-8") as f:
            for line in f:
                m = json.loads(line)
                if datetime.fromisoformat(m["fetched_at"]) < started_at:
                    continue
                if m["status"] == "ok":
                    ok_rows += m.get("n_rows") or 0
                elif m["status"] == "failed":
                    failed += 1
    return ok_rows, failed


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--started-at", type=datetime.fromisoformat, required=True)
    p.add_argument("--status", choices=["success", "failed"], required=True)
    p.add_argument("--notes", default="")
    p.add_argument("--db", default=str(DATA_DIR / "panganwatch.duckdb"))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    tests = test_rows(args.run_id)
    loaded, req_failed = rows_loaded_since(args.started_at)
    con = duckdb.connect(args.db)
    con.execute(DDL)
    con.execute("delete from fct_test_results where run_id = ?", [args.run_id])  # idempotent
    con.execute("delete from fct_pipeline_runs where run_id = ?", [args.run_id])
    if tests:
        con.executemany(
            "insert into fct_test_results values (?, ?, ?, ?, ?, ?, ?, ?)",
            [list(t.values()) for t in tests],
        )
    con.execute(
        "insert into fct_pipeline_runs values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [args.run_id, args.started_at, datetime.now(UTC), args.status, loaded, req_failed,
         sum(t["status"] == "fail" for t in tests), sum(t["status"] == "warn" for t in tests),
         args.notes],
    )
    con.close()
    log.info("logged run %s: %s, %s rows, %s tests", args.run_id, args.status, loaded, len(tests))
    return 0


if __name__ == "__main__":
    sys.exit(main())
