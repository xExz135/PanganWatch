"""Weekly train -> model file -> daily shadow forecasts next to the live baseline."""

from __future__ import annotations

import gzip
from datetime import date

import duckdb
import pandas as pd
import pytest

pytest.importorskip("lightgbm")
from ml import forecast  # noqa: E402
from ml.forecast import publish  # noqa: E402
from ml.train import load, model_path, save, train  # noqa: E402
from tests.ml.test_lgbm import FAST, toy_calendar  # noqa: E402
from tests.ml.test_live_loop import make_db  # noqa: E402
from tests.ml.test_routed import chili_only_hint  # noqa: E402

H = [1, 7]
RUN = date(2025, 3, 3)
VERSION = "lgbm_routed-20250302-test123"


@pytest.fixture
def trained(panel):
    hist = panel[panel["date"] < pd.Timestamp(RUN)]
    feats = chili_only_hint(panel)
    feats = feats[feats["date"] < pd.Timestamp(RUN)]
    return train(hist, feats, toy_calendar(panel), horizons=H, params=FAST)


@pytest.fixture
def model_dir(tmp_path, trained, panel):
    d = tmp_path / "models"
    save(trained, model_path(model_dir=d), VERSION, panel["date"].max())
    return d


@pytest.fixture
def con(tmp_path, panel):
    c = make_db(tmp_path / "shadow.duckdb", panel[panel["date"] < pd.Timestamp(RUN)])
    feats = chili_only_hint(panel)
    feats = feats[feats["date"] < pd.Timestamp(RUN)]
    cal = toy_calendar(panel)
    c.register("f", feats)
    c.register("d", cal)
    c.execute("create table fct_features as select * from f")
    c.execute("create table dim_date as select * from d")
    yield c
    c.close()


def test_saved_model_forecasts_exactly_like_the_trained_one(trained, model_dir, panel):
    hist = panel[panel["date"] < pd.Timestamp(RUN)]
    # the daily job loads only the latest feature rows; category codes must still line up
    recent = chili_only_hint(panel)
    recent = recent[(recent["date"] >= "2025-02-10") & (recent["date"] < pd.Timestamp(RUN))]
    loaded, version = load(model_path(model_dir=model_dir), recent, toy_calendar(panel))
    assert version == VERSION
    assert loaded.use_model == trained.use_model
    a = trained.with_baseline(hist, H).predict(hist, RUN, H)
    b = loaded.with_baseline(hist, H).predict(hist, RUN, H)
    k = ["commodity_id", "province_id", "horizon_days"]
    a, b = a.sort_values(k, ignore_index=True), b.sort_values(k, ignore_index=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False)


def test_shadow_is_published_next_to_the_live_model(con, model_dir):
    live = publish(con, RUN, "naive", today=RUN)
    shadow = publish(con, RUN, "lgbm_routed", today=RUN, model_dir=model_dir)
    assert live > 0 and shadow == live  # same series and horizons
    versions = con.execute("select distinct model_version from fct_forecast").df()
    assert set(versions["model_version"].str.split("-").str[0]) == {"naive", "lgbm_routed"}
    assert VERSION in set(versions["model_version"])
    # idempotent per model
    assert publish(con, RUN, "lgbm_routed", today=RUN, model_dir=model_dir) == 0
    assert publish(con, RUN, "naive", today=RUN) == 0


def test_no_model_file_means_no_shadow_forecasts(con, tmp_path):
    assert publish(con, RUN, "lgbm_routed", today=RUN, model_dir=tmp_path / "empty") == 0
    assert publish(con, RUN, "naive", today=RUN) > 0


def test_a_broken_shadow_model_never_fails_the_daily_job(tmp_path, panel, monkeypatch):
    db = tmp_path / "daily.duckdb"
    make_db(db, panel[panel["date"] < pd.Timestamp(RUN)]).close()
    broken = tmp_path / "broken.json.gz"
    with gzip.open(broken, "wt") as f:
        f.write("not a model")
    monkeypatch.setattr("ml.train.model_path", lambda name, model_dir=None: broken)
    monkeypatch.setattr(forecast, "today_wib", lambda: RUN)
    assert forecast.main(["--date", RUN.isoformat(), "--db", str(db)]) == 0
    c = duckdb.connect(str(db))
    rows = c.execute("select distinct model_version from fct_forecast").fetchall()
    c.close()
    assert [r[0].split("-")[0] for r in rows] == ["naive"]
