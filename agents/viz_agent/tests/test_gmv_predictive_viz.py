from __future__ import annotations

from agents.viz_agent.viz_planner import (
    VizChartTask,
    _enrich_gmv_predictive_charts,
    _is_placeholder_forecast_sql_run,
)


def test_detect_placeholder_forecast_sql_run():
    run = {
        "execute_sql_json": (
            '{"ok": true, "column_profiles": [{"name": "week"}, {"name": "forecast_gmv"}], '
            '"row_count_returned": 6}'
        ),
        "analysis_result": {"business_summary": "占位语句，输出NULL预测"},
    }
    assert _is_placeholder_forecast_sql_run(run) is True


def test_enrich_adds_forecast_line_for_monthly_gmv():
    sql_runs = [
        {
            "execute_sql_json": (
                '{"ok": true, "column_profiles": ['
                '{"name": "year_month"}, {"name": "gmv_total"}], '
                '"row_count_returned": 26}'
            ),
        }
    ]
    charts = _enrich_gmv_predictive_charts(
        user_query="预测未来 6 周销售额并解读趋势",
        intent="predictive",
        charts=[],
        sql_runs=sql_runs,
    )
    assert len(charts) == 1
    assert charts[0].include_forecast is True
    assert charts[0].chart_type_hint == "line"
