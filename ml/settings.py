"""Load ml/settings.yaml once."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

SETTINGS_PATH = Path(__file__).with_name("settings.yaml")


@cache
def settings() -> dict:
    with SETTINGS_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
