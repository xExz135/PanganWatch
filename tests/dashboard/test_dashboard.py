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


def add_lebaran_tables(path: Path) -> None:
    """Minimal A5 tables: chili +35% in Ramadan week 1, back to +2% before Lebaran."""
    con = duckdb.connect(str(path))
    phases = [(1, "60-46 days before", 104), (2, "45-31 days before", 121),
              (3, "Ramadan week 1", 135), (4, "Ramadan weeks 2-3", 104),
              (5, "Last week before Lebaran", 102), (6, "Lebaran + 0-13 days", 106),
              (7, "Lebaran + 14-30 days", 105)]
    con.execute("""create table ana_a5_lebaran_phases (commodity_id varchar, phase_order int,
                   phase varchar, index_median double, index_min double, index_max double,
                   n_years bigint)""")
    con.executemany(
        "insert into ana_a5_lebaran_phases values ('cabai_rawit_merah', ?, ?, ?, ?, ?, 5)",
        [(o, name, v, v - 10, v + 10) for o, name, v in phases])
    con.execute("""create table ana_a5_lebaran_curve as
                   select 'cabai_rawit_merah' as commodity_id, d as event_day,
                          100.0 + d % 7 as index_median, 95.0 as index_min, 110.0 as index_max,
                          5::bigint as n_years
                   from range(-60, 31) t(d)""")
    con.execute("""create table ana_a5_lebaran_daily as
                   select 'cabai_rawit_merah' as commodity_id, y as lebaran_year
                   from range(2022, 2027) t(y)""")
    con.close()


def test_insights_waits_for_analysis_tables(gold, monkeypatch):
    at = run_page(gold, monkeypatch, "views/insights.py")
    assert any("next data update" in i.value for i in at.info)


def test_insights_lebaran_tab(gold, monkeypatch):
    add_lebaran_tables(gold)
    at = run_page(gold, monkeypatch, "views/insights.py")
    assert at.title[0].value == "Insights"
    charts = at.get("plotly_chart")
    assert len(charts) == 2  # overview heatmap + one commodity's curve
    assert "+35% in Ramadan's first week" in charts[1].proto.spec
    assert "+2% in the last week before Lebaran" in charts[1].proto.spec


def test_today_ignores_a_day_when_few_provinces_reported(gold, monkeypatch):
    # a holiday: only Jakarta reports, at double the price; it must not become "national"
    con = duckdb.connect(str(gold))
    con.execute("""insert into fct_daily_price values
                   (?, 'minyak_goreng_curah', 31, 'traditional', 36000, 3)""",
                [LATEST + timedelta(days=1)])
    con.close()
    at = run_page(gold, monkeypatch)
    assert at.subheader[0].value == f"National prices on {LATEST:%d %b %Y}"
    oil = [m for m in at.metric if m.value == "Rp 18,000"]
    assert oil, [m.value for m in at.metric]


def test_insights_volatility_tab(gold, monkeypatch):
    con = duckdb.connect(str(gold))
    con.execute("""
        create table ana_a6_volatility as select * from (values
            ('national', null, 'cabai_rawit_merah', 0.23, 230, 1000, 0.037, 0.02, 34.0, false,
             'high'),
            ('national', null, 'minyak_goreng_curah', 0.0, 0, 1000, 0.006, 0.002, 34.0, false,
             'low'),
            ('province', 31, 'cabai_rawit_merah', 0.46, 460, 1000, 0.05, 0.03, 3.0, false,
             'high'),
            ('province', 35, 'cabai_rawit_merah', 0.14, 140, 1000, 0.03, 0.02, 2.0, false,
             'high')
        ) t(geo_level, province_id, commodity_id, spike_share, spike_days, n_days,
            volatility_daily, volatility_90d, median_reporting, is_thin, risk_segment)
    """)
    con.close()
    at = run_page(gold, monkeypatch, "views/insights.py")
    specs = [c.proto.spec for c in at.get("plotly_chart")]
    assert any("only 1 of 2 foods jumped 15%+" in s for s in specs)
    assert any("from 14% of days in Jawa Timur to 46% in DKI Jakarta" in s for s in specs)


def test_insights_margins_tab(gold, monkeypatch):
    con = duckdb.connect(str(gold))
    con.execute("""
        create table ana_a1_margins_summary as select * from (values
            ('cabai_rawit_merah', 0.70, 0.84, 27.0, false, 0.76, 0.67),
            ('minyak_goreng_curah', 0.86, 0.93, 6.0, true, 0.86, 0.88)
        ) t(commodity_id, producer_share, wholesale_share, median_provinces, is_thin,
            producer_share_first_12m, producer_share_last_12m)
    """)
    con.execute("""
        create table ana_a1_margins_monthly as
        select 'cabai_rawit_merah' as commodity_id, date '2026-01-01' + interval (m) month
               as month, 0.7 as producer_share, 0.84 as wholesale_share, 27 as n_provinces
        from range(0, 10) t(m)
    """)
    con.close()
    at = run_page(gold, monkeypatch, "views/insights.py")
    specs = [c.proto.spec for c in at.get("plotly_chart")]
    assert any("producer share fell from 76% to 67%" in s for s in specs)
    assert any("Left out" in c.value and "Cooking oil" in c.value for c in at.caption)


def test_insights_price_ceiling_tab(gold, monkeypatch):
    con = duckdb.connect(str(gold))
    con.execute("""
        create table ana_a4_compliance_regulation as select * from (values
            ('cabai_rawit_merah', 'traditional', 'Perbapanas 12/2024', 'HAP',
             date '2024-09-26', date '2026-10-16', 2, 0.6, 0.39, 1, 57000, 57000,
             'regulation_text', 'https://example.org/reg')
        ) t(commodity_id, market_tier, regulation, price_type, first_date, last_date,
            n_provinces, share_above, median_excess_when_above, n_provinces_mostly_above,
            reference_min_idr, reference_max_idr, source_kind, source_url)
    """)
    con.execute("""
        create table ana_a4_compliance_province as select * from (values
            ('cabai_rawit_merah', 31, 'traditional', 0.7, 120, 3),
            ('cabai_rawit_merah', 35, 'traditional', 0.5, 40, 0)
        ) t(commodity_id, province_id, market_tier, share_above, longest_streak_days,
            current_streak_days)
    """)
    con.execute("""
        create table ana_a4_compliance_monthly as
        select 'cabai_rawit_merah' as commodity_id, p as province_id,
               'traditional' as market_tier, date '2026-01-01' + interval (m) month as month,
               20 as n_days, 0.6 as share_above, 'Perbapanas 12/2024' as regulations
        from range(0, 6) t(m), (values (31), (35)) v(p)
    """)
    con.close()
    at = run_page(gold, monkeypatch, "views/insights.py")
    specs = [c.proto.spec for c in at.get("plotly_chart")]
    assert any("longest run above the reference 120 published days (DKI Jakarta)" in s
               for s in specs)


def test_insights_transmission_tab(gold, monkeypatch):
    con = duckdb.connect(str(gold))
    con.execute("""
        create table ana_a2_transmission_summary as select * from (values
            ('cabai_rawit_merah', 27, 0.61, -0.49, 0.66, -0.60, 0.06, 0.0001, 0.65,
             date '2022-04-01', date '2026-09-01')
        ) t(commodity_id, n_provinces, rise_same_month, fall_same_month, rise_total,
            fall_total, p_value_equal_totals, p_value_equal_same_month, r_squared,
            first_month, last_month)
    """)
    con.execute("""
        create table ana_a2_transmission_lags as select * from (values
            ('cabai_rawit_merah', 'rise', 0, 0.61), ('cabai_rawit_merah', 'rise', 1, 0.66),
            ('cabai_rawit_merah', 'rise', 2, 0.66), ('cabai_rawit_merah', 'fall', 0, -0.49),
            ('cabai_rawit_merah', 'fall', 1, -0.58), ('cabai_rawit_merah', 'fall', 2, -0.60)
        ) t(commodity_id, direction, lag_months, cumulative)
    """)
    con.close()
    at = run_page(gold, monkeypatch, "views/insights.py")
    specs = [c.proto.spec for c in at.get("plotly_chart")]
    assert any("Rises reach the market faster than falls for 1 of 1 foods" in s for s in specs)
    assert any("lifts the market price 6.6% within two months" in s for s in specs)


def test_insights_spillover_tab(gold, monkeypatch):
    con = duckdb.connect(str(gold))
    con.execute("alter table dim_province add column production_center_commodities varchar[]")
    con.execute("""update dim_province set production_center_commodities = ['cabai_rawit_merah']
                   where province_id = 35""")
    con.execute("""
        create table ana_a3_spillover as select * from (values
            ('cabai_rawit_merah', 31, 0.57, 0.57, 0, true, 400.0, false)
        ) t(commodity_id, province_id, same_day_correlation, best_correlation, lag_days,
            has_clear_link, km_to_nearest_centre, is_thin)
    """)
    con.close()
    at = run_page(gold, monkeypatch, "views/insights.py")
    specs = [c.proto.spec for c in at.get("plotly_chart")]
    assert any("how closely each province moves with the producing centres" in s
               for s in specs)  # no province beyond 1,500 km in this toy, so no near/far line
