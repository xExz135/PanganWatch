"""Where the live loop keeps its tables: fct_forecast and fct_forecast_ledger.

Both are append-only (TEAM.md §3.1). They live in the shared DuckDB file next to the dbt
tables; dbt never rebuilds them, and the daily workflow restores and publishes the whole
file, so the track record carries over from run to run.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIB = timezone(timedelta(hours=7))  # no daylight saving in Indonesia

FORECAST_DDL = """
create table if not exists fct_forecast (
    run_date      date      not null,  -- forecast issued on this day, from data dated before it
    target_date   date      not null,  -- run_date + horizon_days
    horizon_days  integer   not null,
    commodity_id  varchar   not null,
    province_id   integer   not null,
    model_version varchar   not null,
    q10           bigint    not null,  -- rupiah; q10..q90 is the 80% range
    q50           bigint    not null,
    q90           bigint    not null,
    created_at    timestamp not null   -- UTC
)
"""

LEDGER_DDL = """
create table if not exists fct_forecast_ledger (
    run_date       date      not null,
    target_date    date      not null,
    horizon_days   integer   not null,
    commodity_id   varchar   not null,
    province_id    integer   not null,
    model_version  varchar   not null,
    actual_price   bigint    not null,  -- rupiah, never an imputed price
    abs_error      bigint    not null,  -- |q50 - actual|
    pct_error      double    not null,  -- abs_error / actual, decimal
    in_interval_80 boolean   not null,  -- q10 <= actual <= q90
    scored_at      timestamp not null   -- UTC
)
"""


def default_db() -> str:
    return os.environ.get("PANGANWATCH_DB", str(ROOT / "data" / "panganwatch.duckdb"))


def today_wib() -> date:
    return datetime.now(WIB).date()


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_tables(con) -> None:
    con.execute(FORECAST_DDL)
    con.execute(LEDGER_DDL)


def git_hash() -> str:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha[:7]
    try:
        out = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "nogit"
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def model_version(model_name: str) -> str:
    """e.g. naive-818d9c7: the model's name plus the code it ran from."""
    return f"{model_name}-{git_hash()}"
