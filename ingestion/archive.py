"""Pack / unpack bronze and the database for storage as GitHub Release assets.

A GitHub-hosted runner starts empty, so each run restores data from the `data` release
and uploads what changed (docs/decisions.md). Asset layout:

    bronze-YYYY-MM.tar.gz      raw files whose fetch-date folder is in that month
    bronze-manifests.tar.gz    every source's _manifest.jsonl (+ pipeline run log)
    panganwatch.duckdb.gz      the published database (last good build)

    python -m ingestion.archive unpack --src dist          # restore before a run
    python -m ingestion.archive pack --out out             # current month + manifests
    python -m ingestion.archive pack --out out --all       # every month (first upload)
    python -m ingestion.archive pack-db --out out          # database only
"""

from __future__ import annotations

import argparse
import gzip
import logging
import re
import shutil
import sys
import tarfile
from pathlib import Path

from ingestion.config import BRONZE_DIR, DATA_DIR
from ingestion.pihps import today_wib

log = logging.getLogger(__name__)

DB_NAME = "panganwatch.duckdb"
DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def month_dirs(bronze: Path) -> dict[str, list[Path]]:
    """Fetch-date folders (source/YYYY-MM-DD) grouped by YYYY-MM."""
    months: dict[str, list[Path]] = {}
    for d in sorted(bronze.glob("*/*")):
        if d.is_dir() and DAY_DIR.match(d.name):
            months.setdefault(d.name[:7], []).append(d)
    return months


def pack(out: Path, months: list[str] | None, bronze: Path = BRONZE_DIR) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    by_month = month_dirs(bronze)
    written = []
    for month in months if months is not None else sorted(by_month):
        dirs = by_month.get(month, [])
        if not dirs:
            continue
        path = out / f"bronze-{month}.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            for d in dirs:
                tar.add(d, arcname=d.relative_to(bronze).as_posix())
        written.append(path)
    path = out / "bronze-manifests.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for m in sorted(bronze.glob("*/_*.jsonl")):
            tar.add(m, arcname=m.relative_to(bronze).as_posix())
    written.append(path)
    for p in written:
        log.info("packed %s (%.1f MB)", p.name, p.stat().st_size / 1e6)
    return written


def pack_db(out: Path, db: Path = DATA_DIR / DB_NAME) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{DB_NAME}.gz"
    with db.open("rb") as src, gzip.open(path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    log.info("packed %s (%.1f MB)", path.name, path.stat().st_size / 1e6)
    return path


def unpack(src: Path, bronze: Path = BRONZE_DIR, data: Path = DATA_DIR) -> None:
    bronze.mkdir(parents=True, exist_ok=True)
    for tar_path in sorted(src.glob("bronze-*.tar.gz")):
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(bronze, filter="data")  # "data" filter blocks path traversal
        log.info("restored %s", tar_path.name)
    db_gz = src / f"{DB_NAME}.gz"
    if db_gz.exists():
        with gzip.open(db_gz, "rb") as s, (data / DB_NAME).open("wb") as d:
            shutil.copyfileobj(s, d)
        log.info("restored %s", DB_NAME)


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pk = sub.add_parser("pack")
    pk.add_argument("--out", type=Path, required=True)
    pk.add_argument("--all", action="store_true", help="every month, not just the current one")
    sub.add_parser("pack-db").add_argument("--out", type=Path, required=True)
    sub.add_parser("unpack").add_argument("--src", type=Path, required=True)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "pack":
        pack(args.out, None if args.all else [today_wib().strftime("%Y-%m")])
    elif args.cmd == "pack-db":
        pack_db(args.out)
    else:
        unpack(args.src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
