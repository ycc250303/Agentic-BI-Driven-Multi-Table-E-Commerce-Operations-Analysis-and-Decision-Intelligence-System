from __future__ import annotations

import pandas as pd

from agents.viz_agent.run import plan_with_llm
from agents.viz_agent.schema import VizPlan
from agents.viz_agent.plan.viz_planner import VizChartTask, VizSuitePlan, plan_viz_suite


class _StructuredModel:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload
        self.error = error

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        if self.error is not None:
            raise self.error
        return self.payload


def test_plan_with_llm_uses_structured_output():
    df = pd.DataFrame({"state": ["SP", "RJ"], "gmv": [1.0, 2.0]})
    plan, raw = plan_with_llm(
        "各州销售额对比",
        df,
        [],
        "",
        model=_StructuredModel(
            VizPlan(
                chart_type="bar",
                title="各州GMV",
                x_column="state",
                y_column="gmv",
                reasoning="类别对比",
            )
        ),
    )
    assert plan.chart_type == "bar"
    assert plan.x_column == "state"
    assert '"chart_type"' in raw and "bar" in raw


def test_plan_viz_suite_falls_back_with_reason_on_schema_failure():
    plan = plan_viz_suite(
        user_query="各州销售额对比",
        intent="descriptive",
        sql_runs=[
            {
                "question": "各州销售额对比",
                "execute_sql_json": (
                    '{"ok": true, "column_profiles": ['
                    '{"name": "state"}, {"name": "gmv"}], '
                    '"row_count_returned": 2}'
                ),
            }
        ],
        model=_StructuredModel(error=ValueError("bad schema")),
    )
    assert plan.needs_visualization is True
    assert "LLM 结构化输出失败" in plan.reasoning


def test_plan_viz_suite_llm_success_keeps_charts():
    payload = VizSuitePlan(
        needs_visualization=True,
        reasoning="按州对比",
        charts=[
            VizChartTask(
                title="各州GMV",
                rationale="对比",
                data_source="sql_run",
                sql_run_index=0,
                chart_type_hint="bar",
            )
        ],
    )
    plan = plan_viz_suite(
        user_query="各州销售额对比",
        intent="descriptive",
        sql_runs=[
            {
                "question": "各州销售额对比",
                "execute_sql_json": (
                    '{"ok": true, "column_profiles": ['
                    '{"name": "state", "inferred_type": "string"}, '
                    '{"name": "gmv", "inferred_type": "number"}], '
                    '"row_count_returned": 2}'
                ),
            }
        ],
        model=_StructuredModel(payload),
    )
    assert plan.needs_visualization is True
    assert plan.charts
    assert "LLM 结构化输出失败" not in plan.reasoning
