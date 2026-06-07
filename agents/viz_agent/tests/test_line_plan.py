from __future__ import annotations

import pandas as pd

from agents.viz_agent.line_plan import infer_line_series_column, normalize_line_plan
from agents.viz_agent.render import _ordered_time_categories, _prepare_line_dataframe
from agents.viz_agent.run import heuristic_plan
from agents.viz_agent.schema import VizPlan


def test_normalize_line_plan_infers_customer_state():
    df = pd.DataFrame(
        {
            "year_month": ["2017-01", "2017-02", "2017-01", "2017-02"],
            "customer_state": ["SP", "SP", "RJ", "RJ"],
            "gmv_total": [100.0, 120.0, 50.0, 55.0],
        }
    )
    plan = VizPlan(
        chart_type="line",
        title="趋势",
        x_column="year_month",
        y_column="gmv_total",
    )
    normalized = normalize_line_plan(df, plan)
    assert normalized.category_column == "customer_state"


def test_heuristic_plan_multi_series_line():
    df = pd.DataFrame(
        {
            "year_month": ["2017-01", "2017-02"],
            "customer_state": ["SP", "SP"],
            "gmv_total": [100.0, 120.0],
        }
    )
    plan = heuristic_plan(df, "各州月度趋势")
    assert plan.chart_type == "line"
    assert plan.category_column == "customer_state"


def test_infer_line_series_column_skips_time_column():
    df = pd.DataFrame(
        {
            "year_month": ["2017-01", "2017-02"],
            "customer_state": ["SP", "RJ"],
            "gmv_total": [1.0, 2.0],
        }
    )
    assert infer_line_series_column(df, "year_month", "gmv_total") == "customer_state"


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
            {"year_month": "2017-01", "customer_state": state, "gmv_total": float(100 - int(state[1:]))}
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
