"""Shared helpers for every dashboard page: data access, formatting, colors, page chrome.

The dashboard reads gold tables only (data-analyst.md). Each query opens the database
read-only and closes it at once, so the dashboard never blocks the daily build.
"""

from __future__ import annotations

import gzip
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
LOCAL_DB = ROOT / "data" / "panganwatch.duckdb"
REPO = "xExz135/PanganWatch"
RELEASE_TAG = "data"
DB_ASSET = "panganwatch.duckdb.gz"
GITHUB_URL = f"https://github.com/{REPO}"

V1_COMMODITIES = [
    "cabai_rawit_merah", "cabai_merah_keriting", "bawang_merah", "bawang_putih",
    "beras_medium_1", "telur_ayam_ras", "daging_ayam_ras", "minyak_goreng_curah",
]
TIER_ORDER = ["producer", "wholesale", "traditional", "modern"]
TIER_LABEL = {
    "producer": "Producer", "wholesale": "Wholesale",
    "traditional": "Traditional market", "modern": "Modern retail",
}

# Reference palette (dataviz skill), validated for 4 adjacent series in both modes.
# Color follows the tier, never its rank, so a filter never repaints a line.
TIER_COLORS = {
    "light": {"producer": "#2a78d6", "wholesale": "#eb6834",
              "traditional": "#1baf7a", "modern": "#eda100"},
    "dark": {"producer": "#3987e5", "wholesale": "#d95926",
             "traditional": "#199e70", "modern": "#c98500"},
}
# Diverging blue <-> red with a gray midpoint: price falls = blue, rises = red.
DIVERGING = {
    "light": ["#184f95", "#6da7ec", "#f0efec", "#ec835a", "#d03b3b"],
    "dark": ["#2a78d6", "#5598e7", "#383835", "#ec835a", "#e66767"],
}
# Sequential blue, low -> high. The low end recedes toward the surface in each mode, so
# dark mode runs dark -> light (its own steps, not an automatic flip).
SEQUENTIAL_BLUE = {
    "light": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    "dark": ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
}
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

SOURCES_MD = (
    "Sources: [PIHPS Nasional, Bank Indonesia](https://www.bi.go.id/hargapangan) · "
    "[BPS](https://webapi.bps.go.id) · weather data by [Open-Meteo.com](https://open-meteo.com/) "
    "(CC BY 4.0) · USD/IDR: ECB via [Frankfurter](https://frankfurter.dev)"
)


# --- data access ------------------------------------------------------------------------

@st.cache_resource(ttl=3600, show_spinner="Downloading the latest data…")
def _downloaded_db() -> str:
    """Fetch the published database from the `data` GitHub release (deployed app)."""
    import httpx

    token = os.environ.get("GITHUB_TOKEN") or _secret("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    api = f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE_TAG}"
    release = httpx.get(api, headers=headers, timeout=30).raise_for_status().json()
    asset = next(a for a in release["assets"] if a["name"] == DB_ASSET)
    out = Path(tempfile.gettempdir()) / "panganwatch_dashboard.duckdb"
    with httpx.stream("GET", asset["url"], timeout=300, follow_redirects=True,
                      headers={**headers, "Accept": "application/octet-stream"}) as r:
        r.raise_for_status()
        gz = out.with_suffix(".gz")
        with gz.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    with gzip.open(gz, "rb") as s, out.open("wb") as d:
        shutil.copyfileobj(s, d)
    return str(out)


def _secret(name: str) -> str | None:
    try:
        return st.secrets.get(name)
    except Exception:  # noqa: BLE001 - no secrets file locally
        return None


def db_path() -> str:
    """PANGANWATCH_DB if set, else the local build, else the published release asset."""
    if os.environ.get("PANGANWATCH_DB"):
        return os.environ["PANGANWATCH_DB"]
    if LOCAL_DB.exists():
        return str(LOCAL_DB)
    return _downloaded_db()


@st.cache_data(ttl=600, show_spinner=False)
def _query(sql: str, params: tuple, path: str, version: float) -> pd.DataFrame:
    con = duckdb.connect(path, read_only=True)
    try:
        return con.execute(sql, list(params)).df()
    finally:
        con.close()


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a read-only query; cached until the database file changes (or 10 minutes)."""
    path = db_path()
    try:
        return _query(sql, params, path, os.path.getmtime(path))
    except duckdb.IOException:
        st.warning("The database is being updated right now. Refresh in a minute.")
        st.stop()


def table_exists(name: str) -> bool:
    df = query("select count(*) as n from information_schema.tables where table_name = ?",
               (name,))
    return bool(df["n"].iloc[0])


@st.cache_data(ttl=600, show_spinner=False)
def commodity_names() -> dict[str, str]:
    df = query("select commodity_id, name_en, name_id, unit from dim_commodity")
    return {r.commodity_id: f"{r.name_en} ({r.name_id.strip()})" for r in df.itertuples()}


@st.cache_data(ttl=600, show_spinner=False)
def short_names() -> dict[str, str]:
    """English name only, for tight spaces such as metric cards."""
    df = query("select commodity_id, name_en from dim_commodity")
    return dict(zip(df["commodity_id"], df["name_en"], strict=True))


def units() -> dict[str, str]:
    df = query("select commodity_id, unit from dim_commodity")
    return dict(zip(df["commodity_id"], df["unit"], strict=True))


def province_names() -> dict[int, str]:
    df = query("select province_id, name from dim_province order by name")
    return dict(zip(df["province_id"], df["name"], strict=True))


def live_model() -> str:
    """`live.model` in ml/settings.yaml: the forecast users see (shadow models stay hidden).
    Read line by line because PyYAML is not a dashboard dependency."""
    in_live = False
    for line in (ROOT / "ml" / "settings.yaml").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            in_live = line.rstrip() == "live:"
        elif in_live and line.strip().startswith("model:"):
            return line.split(":", 1)[1].split("#")[0].strip()
    return "naive"


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def latest_price_date() -> date | None:
    df = query("select max(date) as d from fct_daily_price")
    d = df["d"].iloc[0]
    return None if pd.isna(d) else pd.Timestamp(d).date()


# --- formatting (only here: tables keep integers and decimals) -------------------------

def rupiah(value: float | int | None) -> str:
    """Rp 45,000. English separators to match the English UI and decimal-point %."""
    if value is None or pd.isna(value):
        return "–"
    return f"Rp {value:,.0f}"


def pct(value: float | None, signed: bool = True) -> str:
    """0.123 -> +12.3%."""
    if value is None or pd.isna(value):
        return "–"
    return f"{value * 100:+.1f}%" if signed else f"{value * 100:.1f}%"


def per_unit(commodity_id: str) -> str:
    return "per liter" if units().get(commodity_id) == "liter" else "per kg"


def theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # noqa: BLE001 - older Streamlit or no browser context (tests)
        return "light"


# --- page chrome ------------------------------------------------------------------------

def page_header(title: str, question: str) -> None:
    st.title(title)
    st.caption(question)
    pipeline_banner()


def pipeline_banner() -> None:
    """Warn when the latest run failed or the data is behind (spec: 'data delayed')."""
    if not table_exists("fct_pipeline_runs"):
        return
    runs = query("""select status, started_at from fct_pipeline_runs
                    order by started_at desc limit 1""")
    latest = latest_price_date()
    if not runs.empty and runs["status"].iloc[0] == "failed":
        st.warning(
            f"⚠️ **Data delayed.** The latest update failed its quality checks, so this "
            f"page still shows data up to **{latest:%d %b %Y}**.", icon=None,
        )


def footer() -> None:
    latest = latest_price_date()
    st.divider()
    left, right = st.columns([3, 1])
    left.caption(SOURCES_MD)
    right.caption(f"Prices up to **{latest:%d %b %Y}**" if latest else "No price data yet")
    st.caption(f"[Methodology and code on GitHub]({GITHUB_URL})")
