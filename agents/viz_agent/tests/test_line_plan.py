from __future__ import annotations

import pandas as pd

from agents.viz_agent.line_plan import normalize_line_plan
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
