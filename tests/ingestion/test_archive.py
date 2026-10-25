"""Bronze archives round-trip: pack by fetch month, unpack restores files byte for byte."""

from __future__ import annotations

from ingestion import archive


def make_bronze(root):
    files = {
        "pihps/2026-09-30/a.json": b'{"data": []}',
        "pihps/2026-10-01/b.json": b'{"data": [1]}',
        "bps/2026-10-25/c.json": b'{"status": "OK"}',
        "pihps/_manifest.jsonl": b'{"request_key": "x"}\n',
        "pipeline/_runs.jsonl": b'{"run_id": "1"}\n',
    }
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return files


def test_pack_current_month_only(tmp_path):
    make_bronze(tmp_path / "bronze")
    written = archive.pack(tmp_path / "out", ["2026-10"], bronze=tmp_path / "bronze")
    assert sorted(p.name for p in written) == ["bronze-2026-10.tar.gz", "bronze-manifests.tar.gz"]


def test_round_trip(tmp_path):
    files = make_bronze(tmp_path / "bronze")
    archive.pack(tmp_path / "out", None, bronze=tmp_path / "bronze")
    restored = tmp_path / "restored"
    archive.unpack(tmp_path / "out", bronze=restored, data=tmp_path)
    for rel, body in files.items():
        assert (restored / rel).read_bytes() == body


def test_db_round_trip(tmp_path):
    db = tmp_path / "panganwatch.duckdb"
    db.write_bytes(b"duckdb-bytes" * 1000)
    archive.pack_db(tmp_path / "out", db=db)
    target = tmp_path / "data"
    target.mkdir()
    archive.unpack(tmp_path / "out", bronze=tmp_path / "b", data=target)
    assert (target / "panganwatch.duckdb").read_bytes() == db.read_bytes()
