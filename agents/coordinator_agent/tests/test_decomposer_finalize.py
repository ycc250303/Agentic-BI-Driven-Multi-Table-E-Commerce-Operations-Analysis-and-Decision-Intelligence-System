from __future__ import annotations

from agents.coordinator_agent.decomposer import DecomposeResult, finalize_suggested_agents


def test_finalize_adds_nlp_for_predictive_bad_review():
    result = DecomposeResult(
        intent="predictive",
        sub_questions=["预测各品类差评趋势？"],
        suggested_agents=["data_analysis", "visualization", "decision"],
        reasoning="llm",
    )
    out = finalize_suggested_agents(result, "预测各品类差评订单数变化趋势并给出风险预警")
    assert "nlp" in out.suggested_agents
    assert out.suggested_agents.index("nlp") < out.suggested_agents.index("visualization")
