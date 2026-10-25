"""Record a pipeline run and its dbt test results (fct_pipeline_runs, fct_test_results).

Runs after `dbt build` (pass or fail) and reads dbt/target/run_results.json + manifest.json.
Rows are appended to data/bronze/pipeline/_runs.jsonl and _test_results.jsonl (the source
of truth, archived with bronze even when a run fails), then both tables are rebuilt from
those files. Written here, not by dbt, so a failed build still logs.

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
LOG_DIR = BRONZE_DIR / "pipeline"
LAYER_BY_FOLDER = {"staging": "silver", "marts": "gold", "ml": "ml", "analyses": "analyses"}

RUN_COLUMNS = {
    "run_id": "VARCHAR", "started_at": "TIMESTAMPTZ", "finished_at": "TIMESTAMPTZ",
    "status": "VARCHAR", "rows_loaded": "BIGINT", "requests_failed": "BIGINT",
    "tests_failed": "INTEGER", "tests_warned": "INTEGER", "notes": "VARCHAR",
    "logged_at": "TIMESTAMPTZ",
}
TEST_COLUMNS = {
    "run_id": "VARCHAR", "run_at": "TIMESTAMPTZ", "test_name": "VARCHAR",
    "model_name": "VARCHAR", "layer": "VARCHAR", "severity": "VARCHAR", "status": "VARCHAR",
    "failures": "BIGINT", "logged_at": "TIMESTAMPTZ",
}


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

    now = datetime.now(UTC).isoformat()
    tests = [{**t, "logged_at": now} for t in test_rows(args.run_id)]
    loaded, req_failed = rows_loaded_since(args.started_at)
    run = {
        "run_id": args.run_id, "started_at": args.started_at.isoformat(), "finished_at": now,
        "status": args.status, "rows_loaded": loaded, "requests_failed": req_failed,
        "tests_failed": sum(t["status"] == "fail" for t in tests),
        "tests_warned": sum(t["status"] == "warn" for t in tests),
        "notes": args.notes, "logged_at": now,
    }
    append_jsonl(LOG_DIR / "_runs.jsonl", [run])
    append_jsonl(LOG_DIR / "_test_results.jsonl", tests)
    rebuild_tables(args.db)
    log.info("logged run %s: %s, %s rows, %s tests", args.run_id, args.status, loaded, len(tests))
    return 0


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def rebuild_tables(db: str, log_dir: Path = LOG_DIR) -> None:
    """Recreate both tables from the JSONL logs. A re-logged run_id keeps its latest entry."""
    con = duckdb.connect(db)
    for table, file, cols, key in [
        ("fct_pipeline_runs", "_runs.jsonl", RUN_COLUMNS, "run_id"),
        ("fct_test_results", "_test_results.jsonl", TEST_COLUMNS, "run_id, test_name"),
    ]:
        path = log_dir / file
        col_list = ", ".join(cols)
        if not path.exists() or path.stat().st_size == 0:
            ddl = ", ".join(f"{c} {t}" for c, t in cols.items())
            con.execute(f"create or replace table {table} ({ddl})")
            continue
        spec = "{" + ", ".join(f"{c}: '{t}'" for c, t in cols.items()) + "}"
        # all entries of the latest logging of a run (a re-run replaces the earlier one)
        con.execute(f"""
            create or replace table {table} as
            select {col_list} from read_json('{path.as_posix()}',
                format = 'newline_delimited', columns = {spec})
            qualify logged_at = max(logged_at) over (partition by run_id)
                and row_number() over (partition by {key} order by logged_at desc) = 1
        """)
    con.close()


if __name__ == "__main__":
    sys.exit(main())
