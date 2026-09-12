from __future__ import annotations

from unittest.mock import patch

from agents.coordinator_agent.orchestration.nodes import nlp_node
from agents.coordinator_agent.orchestration.upstream_ensure import ensure_upstream_payloads


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
    with patch("agents.coordinator_agent.orchestration.upstream_ensure.ReviewInsightAgent") as mock_cls:
        mock_cls.return_value.run.return_value = fake_insights
        patch_out = ensure_upstream_payloads(state)

    assert patch_out["review_insights"] == fake_insights
    assert patch_out["nlp_result"] == fake_insights
    assert patch_out["agents_done"]["nlp"] is True


def test_nlp_node_skips_run_when_insights_exist():
    existing = {"summary": "会话缓存的差评主题"}
    with patch("agents.coordinator_agent.orchestration.nodes.ReviewInsightAgent") as mock_cls:
        out = nlp_node({"review_insights": existing, "user_query": "差评原因"})

    mock_cls.assert_not_called()
    assert out["review_insights"] is existing
    assert out["nlp_result"] == existing
    assert out["agents_done"]["nlp"] is True


def test_nlp_node_writes_nlp_result_from_run():
    fake = {"summary": "新洞察", "topic_distribution": {"delivery_delay": 3}}
    with patch("agents.coordinator_agent.orchestration.nodes.ReviewInsightAgent") as mock_cls:
        mock_cls.return_value.run.return_value = fake
        out = nlp_node({"user_query": "差评原因"})

    mock_cls.return_value.run.assert_called_once()
    assert out["review_insights"] == fake
    assert out["nlp_result"] == fake
    assert out["agents_done"]["nlp"] is True
