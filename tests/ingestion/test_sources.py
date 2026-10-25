"""Offline tests for the BPS, weather and FX fetchers, secret handling and the run logger."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ingestion import bps, config, fx, pipeline_log, store, weather
from ingestion.http import Response
from ingestion.manifest import Manifest

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


# --- shape checks -----------------------------------------------------------------------

def test_bps_shapes():
    assert bps.validate_shape(sample("bps_cpi_food_2025_trimmed.json"))[:2] == ("ok", 72)
    assert bps.validate_shape(b'{"status":"OK","data-availability":"list-not-available"}')[0] \
        == "empty"
    status, _, err = bps.validate_shape(
        b'{"status":"Error","message":"Request rate limit exceeded."}')
    assert status == "failed" and "rate limit" in err


def test_weather_shapes():
    assert weather.validate_shape(sample("weather_jakarta_10d.json"))[:2] == ("ok", 10)
    assert weather.validate_shape(b'{"error": true, "reason": "bad date"}')[0] == "failed"
    # the real failure seen on 2026-10-25: body cut off mid-stream
    assert weather.validate_shape(b"Unexpected error while streaming data")[0] == "failed"


def test_fx_shapes():
    assert fx.validate_shape(sample("fx_usdidr_week.json"))[:2] == ("ok", 5)
    assert fx.validate_shape(b'{"rates": {"2026-10-01": {"EUR": 1}}}')[0] == "failed"


def test_bps_plan_refetches_only_recent_years():
    keys = [j["request_key"] for j in bps.plan(date(2026, 10, 25)) if j["var_id"] == 2212]
    assert keys == ["bps|2212|2024", "bps|2212|2025|2026-10-25", "bps|2212|2026|2026-10-25"]


# --- secrets never reach logs, manifests or errors -------------------------------------

class FakeClient:
    def __init__(self, body: bytes = b"{}", status: int = 200, exc: Exception | None = None):
        self.body, self.status, self.exc = body, status, exc

    def get(self, url, params=None):
        if self.exc:
            raise self.exc
        return Response(status=self.status, body=self.body, url=url)


def test_secret_is_redacted_from_manifest_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("BPS_API_KEY", "SECRET123")
    monkeypatch.setattr(store, "BRONZE_DIR", tmp_path)
    manifest = Manifest("bps", root=tmp_path)
    row = store.fetch_to_bronze(
        FakeClient(exc=RuntimeError("giving up on https://x/key/SECRET123/")), manifest,
        source="bps", request_key="k", kind="bps", url="https://x/key/SECRET123/",
        params={"var_id": 1}, file_stem="f", validate=bps.validate_shape,
    )
    assert row["status"] == "failed"
    assert "SECRET123" not in manifest.path.read_text(encoding="utf-8")


def test_redact_masks_known_secrets(monkeypatch):
    monkeypatch.setenv("BPS_API_KEY", "abc123")
    assert config.redact("url/key/abc123/") == "url/key/***/"


def test_dotenv_does_not_override_real_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("PW_TEST_VAR=from_file\n# comment\n")
    monkeypatch.setenv("PW_TEST_VAR", "from_env")
    config.load_dotenv(env)
    import os
    assert os.environ["PW_TEST_VAR"] == "from_env"


# --- run logger -------------------------------------------------------------------------

def test_pipeline_log_maps_tests_to_layers(tmp_path):
    (tmp_path / "run_results.json").write_text(json.dumps({
        "metadata": {"generated_at": "2026-10-25T07:30:00Z"},
        "results": [
            {"unique_id": "model.p.stg_x", "status": "success"},
            {"unique_id": "test.p.t1", "status": "pass", "failures": 0},
            {"unique_id": "test.p.t2", "status": "warn", "failures": 5},
            {"unique_id": "test.p.t3", "status": "fail", "failures": 2},
        ],
    }))
    (tmp_path / "manifest.json").write_text(json.dumps({"nodes": {
        "model.p.stg_x": {"name": "stg_x", "original_file_path": "models/staging/stg_x.sql"},
        "model.p.fct_y": {"name": "fct_y", "original_file_path": "models/marts/fct_y.sql"},
        "test.p.t1": {"name": "t1", "attached_node": "model.p.stg_x", "config": {}},
        "test.p.t2": {"name": "t2", "attached_node": "model.p.fct_y",
                      "config": {"severity": "WARN"}},
        "test.p.t3": {"name": "t3", "depends_on": {"nodes": ["model.p.fct_y"]},
                      "config": {"severity": "ERROR"}},
    }}))
    rows = pipeline_log.test_rows("r1", target=tmp_path)
    got = [(r["test_name"], r["layer"], r["severity"], r["status"], r["failures"]) for r in rows]
    assert got == [
        ("t1", "silver", "error", "pass", 0),
        ("t2", "gold", "warn", "warn", 5),
        ("t3", "gold", "error", "fail", 2),
    ]


def test_pipeline_log_without_build_output(tmp_path):
    assert pipeline_log.test_rows("r1", target=tmp_path) == []
