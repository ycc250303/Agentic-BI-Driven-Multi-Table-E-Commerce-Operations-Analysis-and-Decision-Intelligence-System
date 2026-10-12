from __future__ import annotations

import json

from agents.sql_agent.tools.result_shape import scalar_result_shape_brief


def test_scalar_result_shape_brief_flags_multirow():
    plan = json.dumps(
        {
            "query_for_sql": "q",
            "sub_questions": [
                {
                    "id": "q1",
                    "question_zh": "全平台 GMV",
                    "metric_key": "total_gmv",
                    "dimensions": [],
                    "aggregation": "",
                    "scope": {"kind": "platform"},
                }
            ],
            "hit_pre_agg_view": False,
            "candidate_views": [],
            "confidence": 0.9,
        }
    )
    exec_json = json.dumps(
        {
            "ok": True,
            "results": [{"index": 0, "ok": True, "row_count_returned": 12}],
        }
    )
    brief = scalar_result_shape_brief(plan, exec_json)
    assert "12 行" in brief
    exec_ok = json.dumps(
        {"ok": True, "results": [{"index": 0, "ok": True, "row_count_returned": 1}]}
    )
    assert scalar_result_shape_brief(plan, exec_ok) == ""
