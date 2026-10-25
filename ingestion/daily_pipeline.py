"""The daily job, in TEAM.md §3.3 order. Same command on a laptop, a VPS or GitHub Actions.

    1  ingest     PIHPS (rolling window) + BPS + weather + FX         -> bronze
    2  dbt build  models and tests together                           -> silver, gold
       (stop here on any error-level failure: steps 3-6 and publish are skipped,
        so yesterday's published data stays live)
    3-6           ml.ledger, ml.forecast, ml.spike_classifier predict, decision.policy
                  (other roles' entry points; skipped while their module doesn't exist)
    log           fct_pipeline_runs + fct_test_results, always

Publishing (step 7) is a separate workflow step, decided in docs/owner_requests.md #8.

    python -m ingestion.daily_pipeline [--date YYYY-MM-DD] [--skip-ingest]
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import subprocess
import sys
from datetime import UTC, date, datetime

from ingestion.config import ROOT
from ingestion.pihps import today_wib

log = logging.getLogger(__name__)

INGEST = [
    ["ingestion.run_daily"],
    ["ingestion.bps"],
    ["ingestion.weather", "daily"],
    ["ingestion.fx", "daily"],
]
DOWNSTREAM = [  # (module, extra args) - owned by DS; called, never edited (TEAM.md §2)
    ("ml.ledger", []),
    ("ml.forecast", []),
    ("ml.spike_classifier", ["predict"]),
    ("decision.policy", []),
]


def run(cmd: list[str], cwd=ROOT) -> bool:
    log.info("$ %s", " ".join(cmd))
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(cmd, cwd=cwd, env=env).returncode == 0


def module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=date.fromisoformat, default=today_wib())
    p.add_argument("--skip-ingest", action="store_true", help="rebuild from existing bronze")
    p.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID")
                   or f"local-{datetime.now(UTC):%Y%m%dT%H%M%S}")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    started = datetime.now(UTC)
    py = sys.executable
    day = ["--date", args.date.isoformat()]
    notes: list[str] = []

    if not args.skip_ingest:
        for step in INGEST:
            if not run([py, "-m", *step, *day]):
                notes.append(f"{step[0]} had failures")  # partial data is still usable

    dbt = str(ROOT / ".venv" / "Scripts" / "dbt.exe") if os.name == "nt" else "dbt"
    built = run([dbt, "build", "--profiles-dir", "."], cwd=ROOT / "dbt")
    if not built:
        notes.append("dbt build failed: downstream steps and publish skipped")
    else:
        for module, extra in DOWNSTREAM:
            if not module_exists(module):
                continue
            if not run([py, "-m", module, *extra, *day]):
                notes.append(f"{module} failed")
                built = False
                break

    status = "success" if built else "failed"
    run([py, "-m", "ingestion.pipeline_log", "--run-id", args.run_id,
         "--started-at", started.isoformat(), "--status", status, "--notes", "; ".join(notes)])
    log.info("pipeline %s%s", status, f" ({'; '.join(notes)})" if notes else "")
    return 0 if built else 1


if __name__ == "__main__":
    sys.exit(main())
