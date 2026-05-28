from __future__ import annotations

import json
from pathlib import Path

from agents.decision_agent.adapters import normalize_state


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def test_normalize_state_from_alternate_upstream_keys():
    raw_state = {
        "user_query": "请给出重点治理建议",
        "analysis_summary": {
            "summary": "配送与卖家表现存在异常。",
            "metric_summary": {
                "gmv": 1000,
                "orders": 20,
                "delivery_on_time_rate": 0.75,
                "average_delivery_days": 9.1,
                "review_score": 3.4,
            },
            "diagnostic_findings": [
                {
                    "topic": "delivery",
                    "metric": "on_time_rate",
                    "scope": "BA",
                    "value": 0.75,
                    "benchmark": 0.84,
                    "gap": -0.09,
                    "evidence": "BA 配送准时率偏低。"
                }
            ],
            "what_if_inputs": {
                "delivery_improvement": {
                    "baseline_avg_delivery_days": 9.1,
                    "baseline_on_time_rate": 0.75,
                    "baseline_delivery_negative_share": 0.3
                }
            }
        },
        "review_insights": {
            "summary": "配送延迟差评较多。",
            "topic_distribution": [
                {"topic": "delivery_delay", "count": 12, "share": 0.26}
            ],
            "complaints_by_state": [{"state": "BA", "negative_rate": 0.28}],
            "sentiment": {"negative_ratio": 0.28}
        },
        "forecast_summary": {
            "summary": "未来增长放缓。",
            "forecast_horizon": "6 weeks",
            "predictions": [1, 2, 3],
            "direction": "down",
            "alerts": ["未来 6 周销售增长放缓"]
        },
        "chart_result": {
            "summary": "图表显示 BA 州配送时长偏高。",
            "figures": [{"title": "delivery"}]
        }
    }
    normalized = normalize_state(raw_state)
    assert normalized["analysis_result"]["kpis"]["on_time_rate"] == 0.75
    assert normalized["nlp_result"]["negative_topics"][0]["topic"] == "delivery_delay"
    assert normalized["forecast_result"]["trend_direction"] == "down"
    assert normalized["visualization_result"]["charts"][0]["title"] == "delivery"


def test_normalize_agent_tpc_review_insights_snapshot():
    review_insights = json.loads(
        (FIXTURE_DIR / "upstream_review_insights_from_agent_tpc.json").read_text(
            encoding="utf-8"
        )
    )
    normalized = normalize_state({"review_insights": review_insights})
    nlp_result = normalized["nlp_result"]
    assert any(topic["topic"] == "delivery_delay" for topic in nlp_result["negative_topics"])
    assert nlp_result["worst_categories"]
    assert nlp_result["sentiment_overview"]["summary"]


def test_normalize_agent_tpc_what_if_snapshot():
    what_if = json.loads(
        (FIXTURE_DIR / "upstream_what_if_from_agent_tpc.json").read_text(
            encoding="utf-8"
        )
    )
    normalized = normalize_state({"what_if_result": what_if})
    out = normalized["what_if_result"]
    assert out["scenario_type"] == "remove_top_bad_sellers"
    assert out["baseline_metrics"]["avg_review_score"] == 4.0346
    assert out["simulated_metrics"]["avg_review_score"] == 4.0488
