from __future__ import annotations

import json

from agents.sql_agent.tools.validate_rewrite_plan import validate_rewrite_plan


def test_state_delay_severity_rejects_delayed_orders_count_only():
    rewrite = {
        "query_for_sql": "平台准时率与各州延迟订单数",
        "sub_questions": [
            {
                "id": "q1",
                "question_zh": "全平台准时交付率",
                "metric_key": "on_time_rate",
                "aggregation": "single_value",
            },
            {
                "id": "q2",
                "question_zh": "各州延迟订单数排名",
                "metric_key": "delayed_orders_count",
                "dimensions": ["customer_state"],
                "aggregation": "top_n",
            },
        ],
        "hit_pre_agg_view": True,
        "candidate_views": ["mv_delivery_perf"],
        "confidence": 0.9,
    }
    out = validate_rewrite_plan(
        "平台整体准时交付率是多少？哪些州延迟最严重？",
        json.dumps(rewrite, ensure_ascii=False),
    )
    assert out.plan_ok is False
    assert "delay_rate" in out.brief


def test_state_delay_severity_accepts_delay_rate():
    rewrite = {
        "query_for_sql": "平台准时率与各州延迟率",
        "sub_questions": [
            {
                "id": "q1",
                "question_zh": "全平台准时交付率",
                "metric_key": "on_time_rate",
                "aggregation": "single_value",
            },
            {
                "id": "q2",
                "question_zh": "各州延迟率排名",
                "metric_key": "delay_rate",
                "dimensions": ["customer_state"],
                "aggregation": "top_n",
            },
        ],
        "hit_pre_agg_view": True,
        "candidate_views": ["mv_delivery_perf"],
        "confidence": 0.9,
    }
    out = validate_rewrite_plan(
        "平台整体准时交付率是多少？哪些州延迟最严重？",
        json.dumps(rewrite, ensure_ascii=False),
    )
    assert out.plan_ok is True
