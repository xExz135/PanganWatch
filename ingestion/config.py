"""Load project config, secrets and standard paths."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
BRONZE_DIR = DATA_DIR / "bronze"
SEEDS_DIR = ROOT / "dbt" / "seeds"

# Env vars whose values must never appear in logs or error messages.
SECRET_ENV_VARS = ("BPS_API_KEY", "MOTHERDUCK_TOKEN")


@cache
def sources() -> dict:
    return yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text(encoding="utf-8"))


@cache
def commodities() -> list[dict]:
    data = yaml.safe_load((CONFIG_DIR / "commodities.yaml").read_text(encoding="utf-8"))
    return data["commodities"]


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Read KEY=VALUE lines from .env into os.environ (real env vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def secret(name: str) -> str:
    load_dotenv()
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set (put it in .env or the environment)")
    return value


def redact(text: str) -> str:
    """Mask any known secret value inside text."""
    for name in SECRET_ENV_VARS:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "***")
    return text
