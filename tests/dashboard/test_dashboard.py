"""Dashboard tests: formatting helpers, and every page rendering headless on a tiny gold DB."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "dashboard" / "app.py"
sys.path.insert(0, str(ROOT / "dashboard"))

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
common = pytest.importorskip("common")

LATEST = date(2026, 10, 16)


# --- formatting -------------------------------------------------------------------------

@pytest.mark.parametrize(("value", "text"), [
    (45000, "Rp 45,000"), (1234567.4, "Rp 1,234,567"), (None, "–"), (float("nan"), "–"),
])
def test_rupiah(value, text):
    assert common.rupiah(value) == text


@pytest.mark.parametrize(("value", "signed", "text"), [
    (0.123, True, "+12.3%"), (-0.05, True, "-5.0%"), (0.2, False, "20.0%"), (None, True, "–"),
])
def test_pct(value, signed, text):
    assert common.pct(value, signed) == text


# --- pages render -----------------------------------------------------------------------

def build_gold(path: Path, *, with_runs: bool, last_run_failed: bool = False) -> None:
    """Gold tables with the contract columns the pages read; 60 days, 2 provinces."""
    con = duckdb.connect(str(path))
    con.execute("""
        create table dim_commodity as
        select * from (values
            ('cabai_rawit_merah', 'Red bird''s-eye chili', 'Cabai Rawit Merah', 'kg'),
            ('minyak_goreng_curah', 'Cooking oil (bulk)', 'Minyak Goreng Curah', 'liter')
        ) t(commodity_id, name_en, name_id, unit)
    """)
    con.execute("""
        create table dim_province as
        select * from (values (31, 'DKI Jakarta', -6.18, 106.83),
                              (35, 'Jawa Timur', -7.25, 112.75)) t(province_id, name, lat, lon)
    """)
    days = [LATEST - timedelta(days=i) for i in range(60)]
    rows = []
    for d in days:
        for prov, base in [(31, 60000), (35, 50000)]:
            # chili jumps 25% in the last week in Jakarta -> a High alert
            spike = 1.25 if (prov == 31 and d > LATEST - timedelta(days=5)) else 1.0
            for tier, f in [("producer", 0.6), ("traditional", 1.0)]:
                rows.append((d, "cabai_rawit_merah", prov, tier, int(base * f * spike), 2))
            rows.append((d, "minyak_goreng_curah", prov, "traditional", 18000, 3))
    con.execute("""create table fct_daily_price (date date, commodity_id varchar,
                   province_id integer, market_tier varchar, price_idr bigint, n_cities bigint)""")
    con.executemany("insert into fct_daily_price values (?, ?, ?, ?, ?, ?)", rows)
    con.execute("""
        create table fct_price_change as
        select p.*,
               p.price_idr::double / lag(p.price_idr, 7) over w - 1 as chg_7d_pct,
               (p.price_idr - avg(p.price_idr) over w28) / nullif(stddev(p.price_idr) over w28, 0)
                   as zscore_28d
        from fct_daily_price as p
        window w as (partition by commodity_id, province_id, market_tier order by date),
               w28 as (partition by commodity_id, province_id, market_tier order by date
                       rows between 27 preceding and current row)
    """)
    if with_runs:
        con.execute("""
            create table fct_pipeline_runs as select * from (values
                ('1', timestamptz '2026-10-15 07:00:00+00', 'success', 1000, 0, 0, 2, ''),
                ('2', timestamptz '2026-10-16 07:00:00+00', ?, 900, 0, ?, 3, '')
            ) t(run_id, started_at, status, rows_loaded, requests_failed, tests_failed,
                tests_warned, notes)
        """, ["failed" if last_run_failed else "success", 1 if last_run_failed else 0])
        con.execute("""
            create table fct_test_results as select * from (values
                ('1', 'not_null_x', 'fct_daily_price', 'gold', 'error', 'pass', 0),
                ('2', 'not_null_x', 'fct_daily_price', 'gold', 'error',
                 'fail', 3),
                ('2', 'jump', 'stg_pihps_price', 'silver', 'warn', 'warn', 5)
            ) t(run_id, test_name, model_name, layer, severity, status, failures)
        """)
    con.close()


def run_page(db: Path, monkeypatch, page: str | None = None) -> AppTest:
    monkeypatch.setenv("PANGANWATCH_DB", str(db))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    if page:
        at.switch_page(page).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


@pytest.fixture
def gold(tmp_path):
    db = tmp_path / "gold.duckdb"
    build_gold(db, with_runs=True)
    return db


def test_today_cards_and_alert(gold, monkeypatch):
    at = run_page(gold, monkeypatch)
    assert at.title[0].value == "Today"
    assert len(at.metric) == 2  # only commodities with data get a card
    text = " ".join(m.value for m in at.markdown)
    assert "🔴 High" in text
    assert "Red bird's-eye chili (Cabai Rawit Merah), DKI Jakarta" in text
    assert "+25.0% in 7 days" in text


def test_explore_renders(gold, monkeypatch):
    at = run_page(gold, monkeypatch, "views/explore.py")
    assert at.title[0].value == "Explore prices"
    assert len(at.get("plotly_chart")) == 2  # tier lines + province map


def test_data_quality_renders_with_runs(gold, monkeypatch):
    at = run_page(gold, monkeypatch, "views/data_quality.py")
    assert any("Last run" in m.label for m in at.metric)


def test_failed_run_shows_delay_banner(tmp_path, monkeypatch):
    db = tmp_path / "gold.duckdb"
    build_gold(db, with_runs=True, last_run_failed=True)
    at = run_page(db, monkeypatch)
    assert any("Data delayed" in w.value for w in at.warning)


def test_pages_work_before_any_logged_run(tmp_path, monkeypatch):
    db = tmp_path / "gold.duckdb"
    build_gold(db, with_runs=False)
    for page in [None, "views/explore.py", "views/data_quality.py"]:
        run_page(db, monkeypatch, page)
