from __future__ import annotations

from pathlib import Path

import pandas as pd

from agents.viz_agent.render.render import (
    _ordered_time_categories,
    _prepare_line_dataframe,
    render_to_png,
)
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


def test_ordered_time_categories_sorts_year_month():
    series = pd.Series(["2017-12", "2017-01", "2017-06"])
    assert _ordered_time_categories(series) == ["2017-01", "2017-06", "2017-12"]


def test_prepare_line_dataframe_aggregates_duplicate_rows():
    df = pd.DataFrame(
        {
            "year_month": ["2017-01", "2017-01", "2017-02"],
            "gmv_total": [10.0, 5.0, 20.0],
        }
    )
    plan = VizPlan(
        chart_type="line",
        x_column="year_month",
        y_column="gmv_total",
    )
    plot_df, x_c, y_c, series_col, x_order, _ = _prepare_line_dataframe(df, plan)
    assert series_col is None
    assert x_order == ["2017-01", "2017-02"]
    indexed = plot_df.set_index(x_c)[y_c]
    assert float(indexed.loc["2017-01"]) == 15.0


def test_prepare_line_dataframe_limits_top_series():
    rows = []
    for state in [f"S{i}" for i in range(12)]:
        rows.append(
            {
                "year_month": "2017-01",
                "customer_state": state,
                "gmv_total": float(100 - int(state[1:])),
            }
        )
    df = pd.DataFrame(rows)
    plan = VizPlan(
        chart_type="line",
        x_column="year_month",
        y_column="gmv_total",
        category_column="customer_state",
    )
    plot_df, _, _, series_col, _, legend_note = _prepare_line_dataframe(df, plan)
    assert series_col == "customer_state"
    assert plot_df[series_col].nunique() == 8
    assert legend_note == "Top 8"


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
