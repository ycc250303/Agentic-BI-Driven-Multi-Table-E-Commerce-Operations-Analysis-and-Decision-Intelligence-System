from __future__ import annotations

from unittest.mock import patch

from agents.coordinator_agent.upstream_ensure import ensure_upstream_payloads


def test_ensure_nlp_runs_when_missing():
    state = {
        "user_query": "Top 10 差评品类及其主要差评原因是什么？",
        "intent": "diagnostic",
        "suggested_agents": ["data_analysis", "nlp", "decision"],
        "agents_done": {"data_analysis": True},
        "sql_runs": [{"ok": True}],
    }
    fake_insights = {
        "summary": "配送延迟占比最高",
        "topic_distribution": {"delivery_delay": 10},
    }
    with patch("agents.coordinator_agent.upstream_ensure.ReviewInsightAgent") as mock_cls:
        mock_cls.return_value.run.return_value = {"review_insights": fake_insights}
        patch_out = ensure_upstream_payloads(state)

    assert patch_out["review_insights"] == fake_insights
    assert patch_out["nlp_result"] == fake_insights
    assert patch_out["agents_done"]["nlp"] is True
