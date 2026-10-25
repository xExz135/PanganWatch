"""Offline tests for the PIHPS scraper: shape checks, idempotency, retries, bronze writes."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from ingestion import pihps
from ingestion.http import PoliteClient, Response
from ingestion.manifest import Manifest

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def sample_bytes() -> bytes:
    return (SAMPLES / "pihps_grid_jakarta_cabai_rawit.json").read_bytes()


# --- validation at the door -------------------------------------------------------------

def test_real_sample_is_ok():
    status, n_rows, error = pihps.validate_shape(sample_bytes())
    assert (status, n_rows, error) == ("ok", 3, None)


def test_empty_data_is_empty_not_failed():
    assert pihps.validate_shape(b'{"data": []}')[0] == "empty"


@pytest.mark.parametrize(
    "body",
    [
        b"<html>maintenance</html>",
        b'{"rows": []}',
        b'{"data": [{"name": "x"}]}',
        b'{"data": [{"name": "x", "level": 2, "2026-10-13": "1"}]}',  # date format changed
    ],
)
def test_changed_shape_fails(body):
    status, _, error = pihps.validate_shape(body)
    assert status == "failed" and error


def test_request_params_match_site():
    p = pihps.grid_params(date(2026, 10, 13), date(2026, 10, 24), "producer", 34)
    assert p["price_type_id"] == 4
    assert p["regency_id"] == "34"
    assert p["tipe_laporan"] == 1
    assert (p["start_date"], p["end_date"]) == ("2026-10-13", "2026-10-24")


# --- idempotency and bronze ---------------------------------------------------------------

class FakeClient:
    def __init__(self, status: int = 200, body: bytes | None = None):
        self.calls = 0
        self.status = status
        self.body = sample_bytes() if body is None else body

    def get(self, url, params=None):
        self.calls += 1
        return Response(status=self.status, body=self.body, url=url)


@pytest.fixture
def bronze(tmp_path, monkeypatch):
    monkeypatch.setattr(pihps, "BRONZE_DIR", tmp_path)
    return tmp_path


def run_once(client, manifest, key="k1"):
    return pihps.fetch_and_store(
        client, manifest, request_key=key, kind="test",
        date_from=date(2026, 10, 13), date_to=date(2026, 10, 24),
        market_tier="traditional", city_id=34,
    )


def test_second_run_skips_and_bronze_is_byte_identical(bronze):
    manifest = Manifest("pihps", root=bronze)
    client = FakeClient()
    row = run_once(client, manifest)
    assert row["status"] == "ok" and row["n_rows"] == 3
    assert (bronze / row["file_path"]).read_bytes() == sample_bytes()

    assert run_once(client, Manifest("pihps", root=bronze)) is None  # re-read from disk
    assert client.calls == 1


def test_failed_request_is_logged_and_retried_next_run(bronze):
    manifest = Manifest("pihps", root=bronze)
    row = run_once(FakeClient(body=b"<html>oops</html>"), manifest)
    assert row["status"] == "failed"
    assert row["params"]["city_id"] == 34
    good = FakeClient()
    assert run_once(good, manifest)["status"] == "ok"
    assert good.calls == 1


def test_manifest_lines_are_json(bronze):
    manifest = Manifest("pihps", root=bronze)
    run_once(FakeClient(), manifest)
    lines = manifest.path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["request_key"] == "k1"


# --- retries ------------------------------------------------------------------------------

def client_with(statuses: list[int], monkeypatch) -> tuple[PoliteClient, list[int]]:
    seen: list[int] = []

    def handler(request):
        code = statuses[len(seen)]
        seen.append(code)
        return httpx.Response(code, content=b'{"data": []}')

    c = PoliteClient(sleep_seconds=0)
    c.backoff = [0.0, 0.0, 0.0]
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("time.sleep", lambda s: None)
    return c, seen


def test_retries_on_5xx_then_succeeds(monkeypatch):
    c, seen = client_with([503, 502, 200], monkeypatch)
    assert c.get("https://example.test").status == 200
    assert seen == [503, 502, 200]


def test_4xx_is_not_retried(monkeypatch):
    c, seen = client_with([403], monkeypatch)
    assert c.get("https://example.test").status == 403
    assert seen == [403]


def test_gives_up_after_all_attempts(monkeypatch):
    c, _ = client_with([500, 500, 500, 500], monkeypatch)
    with pytest.raises(RuntimeError):
        c.get("https://example.test")
