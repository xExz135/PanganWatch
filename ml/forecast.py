"""Publish today's forecasts to fct_forecast (TEAM.md §3.3 step 4).

    python -m ml.forecast [--date YYYY-MM-DD] [--db PATH]

Uses only prices dated before --date, the same rule as the backtest. Append-only and
idempotent per model: if --date already has a model's forecasts, nothing is written, so a
re-run never changes a published forecast. Publishes `live.model` (what users see), then each
`live.shadow` model; a shadow model that fails or has no trained file (ml.train) is skipped
with a warning, never failing the daily job.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ml.baselines import NaiveForecaster, SeasonalNaiveForecaster
from ml.data import load_calendar, load_features, load_history
from ml.settings import settings
from ml.store import default_db, ensure_tables, model_version, today_wib, utc_now

log = logging.getLogger(__name__)

MODELS = {"naive": NaiveForecaster, "seasonal_naive": SeasonalNaiveForecaster}
COLUMNS = ["run_date", "target_date", "horizon_days", "commodity_id", "province_id",
           "q10", "q50", "q90"]


def make_forecast(history: pd.DataFrame, run_date: date, model_name: str,
                  horizons: list[int] | None = None, trained=None) -> pd.DataFrame:
    """Forecast every live series from rows dated before run_date. Prices in whole rupiah.
    `trained` is a model loaded by ml.train (its baseline part is refit here)."""
    horizons = horizons or list(settings()["backtest"]["horizons"])
    if model_name not in MODELS and trained is None:
        raise ValueError(f"unknown live model {model_name!r}; known: {sorted(MODELS)}")
    hist = history[history["date"] < pd.Timestamp(run_date)]
    if hist.empty:
        return pd.DataFrame(columns=COLUMNS)
    fitted = (trained.with_baseline(hist, horizons) if trained is not None
              else MODELS[model_name]().fit(hist, horizons=horizons))
    pred = fitted.predict(hist, run_date, horizons)
    if pred.empty:
        return pd.DataFrame(columns=COLUMNS)
    q50 = np.rint(pred["q50"].to_numpy(dtype=float))
    # A range must contain its median; whole-rupiah rounding can't be allowed to break that.
    q10 = np.minimum(np.rint(pred["q10"].to_numpy(dtype=float)), q50)
    q90 = np.maximum(np.rint(pred["q90"].to_numpy(dtype=float)), q50)
    out = pd.DataFrame({
        "run_date": pd.Timestamp(run_date),
        "target_date": pd.to_datetime(pred["target_date"]),
        "horizon_days": pred["horizon_days"].astype(int),
        "commodity_id": pred["commodity_id"].astype(str),
        "province_id": pred["province_id"].astype(int),
        "q10": q10.astype("int64"), "q50": q50.astype("int64"), "q90": q90.astype("int64"),
    })
    return out.sort_values(["horizon_days", "commodity_id", "province_id"],
                           ignore_index=True)[COLUMNS]


def publish(con, run_date: date, model_name: str | None = None,
            today: date | None = None, model_dir: Path | None = None) -> int:
    """Write run_date's forecasts of one model unless they exist. Returns rows written
    (0 = skipped). Rule models are fit here; others are loaded from ml.train's file.

    A past run_date is skipped: a forecast written after its day would not be a forecast
    (the ledger integrity test in dbt/models/ml/ would also stop the next build).
    """
    model_name = model_name or settings()["live"]["model"]
    today = today or today_wib()
    ensure_tables(con)
    if run_date < today:
        log.warning("not publishing forecasts for past date %s (today is %s)", run_date, today)
        return 0
    (done,) = con.execute("""select count(*) from fct_forecast
                             where run_date = ? and model_version like ?""",
                          [run_date, f"{model_name}-%"]).fetchone()
    if done:
        log.info("%s forecasts for %s already published (%s rows); nothing written",
                 model_name, run_date, done)
        return 0
    trained, version = None, model_version(model_name)
    if model_name not in MODELS:
        from ml.train import load, model_path
        path = model_path(model_name, model_dir)
        if not path.exists():
            log.warning("no trained %s at %s (ml.train runs weekly); skipped", model_name, path)
            return 0
        since = pd.Timestamp(run_date) - timedelta(
            days=settings()["baselines"]["max_staleness_days"] + 1)
        trained, version = load(path, load_features(con, since=since.date()),
                                load_calendar(con))
    history = load_history(con)
    if history.empty:
        log.warning("no price history; nothing to forecast")
        return 0
    fc = make_forecast(history, run_date, model_name, trained=trained)
    if fc.empty:
        raise RuntimeError(f"price history exists but no series could be forecast for "
                           f"{run_date} (all older than the staleness limit?)")
    fc = fc.assign(model_version=version, created_at=utc_now())
    con.register("new_forecast", fc)
    try:
        con.execute("""
            insert into fct_forecast (run_date, target_date, horizon_days, commodity_id,
                province_id, model_version, q10, q50, q90, created_at)
            select run_date::date, target_date::date, horizon_days, commodity_id,
                province_id, model_version, q10, q50, q90, created_at
            from new_forecast
        """)
    finally:
        con.unregister("new_forecast")
    log.info("published %s forecasts for %s (%s, %s series)", len(fc), run_date,
             fc["model_version"].iat[0], fc.groupby(["commodity_id", "province_id"]).ngroups)
    return len(fc)


def main(argv: list[str] | None = None) -> int:
    import duckdb

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", type=date.fromisoformat, default=today_wib())
    ap.add_argument("--db", default=default_db())
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    con = duckdb.connect(args.db)
    try:
        try:
            publish(con, args.date)
        except Exception:
            log.exception("forecast for %s failed", args.date)
            return 1
        for name in settings()["live"].get("shadow") or []:
            try:
                publish(con, args.date, name)
            except Exception:
                log.exception("shadow model %s failed for %s; live forecasts unaffected",
                              name, args.date)
                if os.environ.get("GITHUB_ACTIONS"):  # shows on the run's summary page
                    print(f"::warning::shadow model {name} failed for {args.date}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
