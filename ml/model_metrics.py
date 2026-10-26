"""fct_model_metrics: backtest results per model version (TEAM.md §3.1 contract).

Backtests take about an hour, too long for the workflows, so they run locally and their
summary is committed to ml/backtests/metrics.csv (small; reproducible from the version's git
hash). The daily job loads that file into fct_model_metrics, replacing any rows of the same
model_version, so the table always matches the committed file.

    python -m ml.model_metrics add SCORED_CSV --version backtest-YYYYMMDD-<git> [--models a,b]
    python -m ml.model_metrics publish [--db PATH]

`add` turns a backtest's scored forecasts (ml.backtest --out) into metric rows and merges
them into the committed file.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from ml.store import ROOT, default_db

log = logging.getLogger(__name__)
METRICS_CSV = ROOT / "ml" / "backtests" / "metrics.csv"
COLUMNS = ["model_version", "model_name", "task", "horizon_days", "segment", "commodity_id",
           "metric", "value", "evaluated_at"]

DDL = """
create table if not exists fct_model_metrics (
    model_version varchar   not null,  -- backtest-<date>-<git>: the code that produced it
    model_name    varchar   not null,
    task          varchar   not null,  -- forecast / spike
    horizon_days  integer,
    segment       varchar   not null,  -- all / normal / ramadan_lebaran
    commodity_id  varchar,             -- NULL = all commodities
    metric        varchar   not null,
    value         double,
    evaluated_at  timestamp not null   -- UTC
)
"""


def read(path: Path = METRICS_CSV) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, dtype={"commodity_id": "string", "model_version": "string"})
    df["evaluated_at"] = pd.to_datetime(df["evaluated_at"], utc=True).dt.tz_localize(None)
    return df[COLUMNS]


def add(scored: pd.DataFrame, version: str, models: list[str] | None = None,
        path: Path = METRICS_CSV) -> pd.DataFrame:
    """Evaluate a backtest and merge its rows into the committed file (same version replaced).
    `models` keeps only those models' rows; baselines still count as references."""
    from ml.backtest import evaluate

    m = evaluate(scored, model_version=version)
    if models:
        m = m[m["model_name"].isin(models)]
    m["evaluated_at"] = pd.Timestamp.now("UTC").tz_localize(None).floor("s")
    old = read(path)
    out = pd.concat([old[old["model_version"] != version], m[COLUMNS]], ignore_index=True)
    out = out.sort_values(["model_version", "model_name", "horizon_days", "segment",
                           "commodity_id", "metric"], na_position="first", ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    return out


def publish(con, path: Path = METRICS_CSV) -> int:
    """Load the committed file into fct_model_metrics; idempotent per model_version."""
    con.execute(DDL)
    df = read(path)
    if df.empty:
        return 0
    con.register("new_metrics", df)
    try:
        con.execute("begin")
        con.execute("""delete from fct_model_metrics
                       where model_version in (select distinct model_version from new_metrics)""")
        con.execute(f"insert into fct_model_metrics select {', '.join(COLUMNS)} from new_metrics")
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    finally:
        con.unregister("new_metrics")
    return len(df)


def main(argv: list[str] | None = None) -> int:
    import duckdb

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("scored", type=Path)
    a.add_argument("--version", required=True)
    a.add_argument("--models", help="comma-separated; default all")
    p = sub.add_parser("publish")
    p.add_argument("--db", default=default_db())
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "add":
        scored = pd.read_csv(args.scored, parse_dates=["target_date", "run_date", "cutoff"])
        out = add(scored, args.version, args.models.split(",") if args.models else None)
        log.info("%s now holds %s rows (%s versions)", METRICS_CSV, len(out),
                 out["model_version"].nunique())
    else:
        con = duckdb.connect(args.db)
        try:
            log.info("loaded %s rows into fct_model_metrics", publish(con))
        finally:
            con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
