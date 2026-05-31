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


def test_build_viz_execute_json_has_top_level_csv_path():
    payload = {"data_summary_zh": "摘要", "column_profiles": []}
    row = {"result_csv_path": "/tmp/rank.csv", "row_count_returned": 27}
    raw = build_viz_execute_json(payload, row)
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["result_csv_path"] == "/tmp/rank.csv"
