from __future__ import annotations

import json

from agents.coordinator_agent.adapters import (
    build_viz_execute_json,
    pick_viz_csv_from_exec_payload,
)


def test_pick_viz_csv_from_results():
    payload = {
        "ok": False,
        "results": [
            {"ok": True, "result_csv_path": "/tmp/a.csv", "row_count_returned": 27},
            {"ok": True, "result_csv_path": "/tmp/b.csv", "row_count_returned": 10},
        ],
    }
    assert pick_viz_csv_from_exec_payload(payload) == "/tmp/a.csv"


def test_pick_viz_csv_prefers_ranking_for_bar_hint():
    payload = {
        "ok": True,
        "results": [
            {
                "ok": True,
                "result_csv_path": "/tmp/trend.csv",
                "row_count_returned": 345,
                "data_summary_zh": "共 3 列：year_month, customer_state, gmv_total",
            },
            {
                "ok": True,
                "result_csv_path": "/tmp/rank.csv",
                "row_count_returned": 27,
                "data_summary_zh": "共 2 列：customer_state, gmv_total",
            },
        ],
    }
    assert (
        pick_viz_csv_from_exec_payload(payload, chart_type_hint="bar")
        == "/tmp/rank.csv"
    )
    assert (
        pick_viz_csv_from_exec_payload(payload, chart_type_hint="line")
        == "/tmp/trend.csv"
    )


def test_build_viz_execute_json_has_top_level_csv_path():
    payload = {"data_summary_zh": "摘要", "column_profiles": []}
    row = {"result_csv_path": "/tmp/rank.csv", "row_count_returned": 27}
    raw = build_viz_execute_json(payload, row)
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["result_csv_path"] == "/tmp/rank.csv"
