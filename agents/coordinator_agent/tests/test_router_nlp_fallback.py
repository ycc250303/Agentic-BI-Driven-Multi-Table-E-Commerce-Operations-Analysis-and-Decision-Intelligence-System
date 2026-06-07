from __future__ import annotations

from agents.coordinator_agent.router import _pending_post_sql_agents


def test_pending_includes_nlp_for_predictive_bad_review_even_if_not_suggested():
    state = {
        "user_query": "预测未来各品类差评订单数变化趋势并给出风险预警",
        "intent": "predictive",
        "suggested_agents": ["data_analysis", "visualization", "decision"],
        "agents_done": {"data_analysis": True},
        "sql_runs": [{"ok": True}],
    }
    pending = _pending_post_sql_agents(state)
    assert pending[0] == "nlp"
    assert "visualization" in pending
