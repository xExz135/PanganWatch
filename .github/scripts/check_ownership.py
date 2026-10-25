"""Fail a PR that touches paths outside its author role's ownership (TEAM.md §2, §4).

Usage: python check_ownership.py <head_branch> <base_ref>
The role comes from the branch prefix: de/…, da/…, ds/…. Other prefixes (e.g. owner/…)
are the project owner's and are not restricted.
"""

from __future__ import annotations

import subprocess
import sys
from fnmatch import fnmatch

# Most specific rules first; the first match decides the owner.
RULES: list[tuple[str, str]] = [
    ("dbt/seeds/reference_prices.csv", "da"),
    ("dbt/models/marts/dim_reference_price.*", "da"),
    ("dbt/models/marts/fct_reference_compliance.*", "da"),
    ("dbt/models/analyses/*", "da"),
    ("dbt/models/ml/*", "ds"),
    ("dbt/*", "de"),
    ("config/persona.yaml", "da"),
    ("config/*", "de"),
    ("ingestion/*", "de"),
    ("data/*", "de"),
    ("analytics/*", "da"),
    ("ml/*", "ds"),
    ("decision/scenario.py", "da"),
    ("decision/*", "ds"),
    ("dashboard/*", "da"),
    (".github/*", "de"),
    ("pyproject.toml", "de"),
    ("*.lock", "de"),
    (".pre-commit-config.yaml", "de"),
    (".env.example", "de"),
    (".gitignore", "de"),
    ("tests/ingestion/*", "de"),
    ("tests/dbt/*", "de"),
    ("tests/samples/*", "de"),
    ("tests/ml/*", "ds"),
    ("tests/decision/*", "ds"),
    ("tests/analytics/*", "da"),
    ("tests/dashboard/*", "da"),
    ("tests/scenario/*", "da"),
    ("notebooks/de/*", "de"),
    ("notebooks/da/*", "da"),
    ("notebooks/ds/*", "ds"),
    ("docs/source_notes.md", "de"),
    ("docs/architecture.png", "de"),
    ("docs/findings.md", "da"),
    ("README.md", "da"),  # DE/DS blocks inside it are not checked line by line
    # Shared-by-section or shared-by-protocol files: anyone may touch them.
    ("docs/decisions.md", "*"),
    ("docs/owner_requests.md", "*"),
    ("docs/mistakes/*", "*"),
]


def owner_of(path: str) -> str | None:
    for pattern, owner in RULES:
        if fnmatch(path, pattern):
            return owner
    return None  # unmapped: owner only


def main() -> int:
    branch, base = sys.argv[1], sys.argv[2]
    role = branch.split("/", 1)[0] if "/" in branch else ""
    if role not in {"de", "da", "ds"}:
        print(f"branch '{branch}' has no role prefix; treated as project owner, not checked")
        return 0
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    bad = [p for p in changed if owner_of(p) not in {role, "*"}]
    for p in bad:
        owner = owner_of(p) or "project owner"
        print(f"::error file={p}::{role} may not change {p} (owner: {owner})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
