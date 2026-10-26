"""Weekly retrain of the shadow model (TEAM.md §3.3: Sunday).

    python -m ml.train [--db PATH] [--date YYYY-MM-DD]

Trains `lgbm_routed` on every price published so far (the last `validation_days` are the
validation slice, as in each backtest fold) and saves it to ml/models/lgbm_routed.json.gz:
the LightGBM boosters as text plus everything needed to forecast with them. The file carries
its own version, lgbm_routed-<train date>-<git hash>, which ml.forecast writes as
model_version. The naive part is refit daily from fresh prices, like the live baseline.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from ml.data import load_calendar, load_features, load_history
from ml.lgbm import LGBMForecaster
from ml.routed import RoutedForecaster
from ml.settings import settings
from ml.store import ROOT, default_db, git_hash, today_wib, utc_now

log = logging.getLogger(__name__)
NAME = "lgbm_routed"
FORMAT = 1


def model_path(name: str = NAME, model_dir: Path | None = None) -> Path:
    return (model_dir or ROOT / settings()["models"]["dir"]) / f"{name}.json.gz"


def train(history: pd.DataFrame, features: pd.DataFrame, calendar: pd.DataFrame,
          horizons: list[int] | None = None, params: dict | None = None) -> RoutedForecaster:
    horizons = horizons or list(settings()["backtest"]["horizons"])
    val_days = pd.Timedelta(days=settings()["backtest"]["validation_days"])
    hist = history.assign(date=pd.to_datetime(history["date"]))
    valid = hist[hist["date"] > hist["date"].max() - val_days]
    model = LGBMForecaster(features=features, calendar=calendar,
                           **({"params": params} if params else {}))
    return RoutedForecaster(model=model).fit(hist, valid, horizons=horizons)


def save(routed: RoutedForecaster, path: Path, version: str, data_end) -> None:
    m = routed.model
    doc = {
        "format": FORMAT, "name": routed.name, "version": version,
        "trained_at": utc_now().isoformat(timespec="seconds") + "Z",
        "data_end": str(pd.Timestamp(data_end).date()),
        "quantiles": m.quantiles, "max_staleness_days": m.max_staleness_days,
        "params": m.params, "min_gain": routed.min_gain,
        "use_model": sorted([c, h] for c, h in routed.use_model),
        "widen": {str(h): w for h, w in m.widen.items()},
        "best_rounds": {f"{h}|{q}": r for (h, q), r in m.best_rounds.items()},
        "validation": {str(h): v.to_dict("records") for h, v in m.validation.items()},
        "boosters": {f"{h}|{q}": b.model_to_string() for (h, q), b in m.models.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(doc, f)
    tmp.replace(path)


def load(path: Path, features: pd.DataFrame, calendar: pd.DataFrame
         ) -> tuple[RoutedForecaster, str]:
    """A trained model ready to forecast from `features` (the baseline still needs fitting)."""
    import lightgbm as lgb

    with gzip.open(path, "rt", encoding="utf-8") as f:
        doc = json.load(f)
    if doc.get("format") != FORMAT:
        raise ValueError(f"{path}: unknown model file format {doc.get('format')!r}")

    def hq(key: str) -> tuple[int, float]:
        h, q = key.split("|")
        return int(h), float(q)

    model = LGBMForecaster(
        features=features, calendar=calendar, name="lgbm_quantile",
        quantiles=[float(q) for q in doc["quantiles"]],
        max_staleness_days=int(doc["max_staleness_days"]), params=doc["params"],
        models={hq(k): lgb.Booster(model_str=s) for k, s in doc["boosters"].items()},
        widen={int(h): float(w) for h, w in doc["widen"].items()},
        best_rounds={hq(k): int(r) for k, r in doc["best_rounds"].items()},
        validation={int(h): pd.DataFrame(v) for h, v in doc["validation"].items()},
    )
    routed = RoutedForecaster(model=model, name=doc["name"], min_gain=float(doc["min_gain"]),
                              use_model={(c, int(h)) for c, h in doc["use_model"]})
    return routed, doc["version"]


def main(argv: list[str] | None = None) -> int:
    import duckdb

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=default_db())
    ap.add_argument("--date", type=date.fromisoformat, default=today_wib())
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    con = duckdb.connect(args.db, read_only=True)
    try:
        history, features, calendar = load_history(con), load_features(con), load_calendar(con)
    finally:
        con.close()
    history = history[history["date"] < pd.Timestamp(args.date)]
    features = features[features["date"] < pd.Timestamp(args.date)]
    if history.empty:
        log.error("no price history in %s", args.db)
        return 1
    routed = train(history, features, calendar)
    version = f"{NAME}-{args.date:%Y%m%d}-{git_hash()}"
    path = model_path()
    save(routed, path, version, history["date"].max())
    chosen = sorted({c for c, _ in routed.use_model})
    log.info("saved %s to %s (%.1f MB); LightGBM used for %s commodity-horizons: %s",
             version, path, path.stat().st_size / 1e6, len(routed.use_model), ", ".join(chosen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
