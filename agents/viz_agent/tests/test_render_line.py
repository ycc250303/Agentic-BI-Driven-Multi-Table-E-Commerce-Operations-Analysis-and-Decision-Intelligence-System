from __future__ import annotations

from pathlib import Path

import pandas as pd

from agents.viz_agent.line_plan import normalize_line_plan
from agents.viz_agent.render import render_to_png
from agents.viz_agent.schema import VizPlan


def test_render_multi_series_line_with_state_legend(tmp_path: Path):
    df = pd.DataFrame(
        {
            "year_month": ["2017-01", "2017-02", "2017-01", "2017-02"],
            "customer_state": ["SP", "SP", "RJ", "RJ"],
            "gmv_total": [100.0, 120.0, 50.0, 55.0],
        }
    )
    plan = VizPlan(
        chart_type="line",
        title="2017年各州月度销售额趋势",
        x_column="year_month",
        y_column="gmv_total",
        category_column="customer_state",
    )
    out = tmp_path / "state_trend.png"
    path = render_to_png(df, plan, out)
    assert Path(path).is_file()
    assert Path(path).stat().st_size > 0


def test_render_line_auto_detects_series_without_category_column(tmp_path: Path):
    df = pd.DataFrame(
        {
            "year_month": ["2017-02", "2017-01", "2017-02", "2017-01"],
            "customer_state": ["SP", "SP", "RJ", "RJ"],
            "gmv_total": [120.0, 100.0, 55.0, 50.0],
        }
    )
    plan = normalize_line_plan(
        df,
        VizPlan(
            chart_type="line",
            title="2017年各州月度销售额趋势",
            x_column="year_month",
            y_column="gmv_total",
        ),
    )
    assert plan.category_column == "customer_state"
    path = render_to_png(df, plan, tmp_path / "auto_series.png")
    assert Path(path).is_file()


def test_render_single_series_line_aggregates_duplicate_months(tmp_path: Path):
    df = pd.DataFrame(
        {
            "year_month": ["2017-01", "2017-01", "2017-02"],
            "gmv_total": [100.0, 50.0, 80.0],
        }
    )
    plan = VizPlan(
        chart_type="line",
        title="2017年按月GMV趋势",
        x_column="year_month",
        y_column="gmv_total",
    )
    path = render_to_png(df, plan, tmp_path / "monthly.png")
    assert Path(path).is_file()


def test_render_scalar_kpi_bar(tmp_path: Path):
    df = pd.DataFrame({"gmv_total_2017": [7090569.24]})
    plan = VizPlan(
        chart_type="bar",
        title="2017年GMV总金额",
        y_column="gmv_total_2017",
    )
    out = tmp_path / "scalar_kpi.png"
    path = render_to_png(df, plan, out)
    assert Path(path).is_file()
