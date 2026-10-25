"""Load project config and resolve standard paths."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
BRONZE_DIR = DATA_DIR / "bronze"
SEEDS_DIR = ROOT / "dbt" / "seeds"


@cache
def sources() -> dict:
    return yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text(encoding="utf-8"))


@cache
def commodities() -> list[dict]:
    data = yaml.safe_load((CONFIG_DIR / "commodities.yaml").read_text(encoding="utf-8"))
    return data["commodities"]
