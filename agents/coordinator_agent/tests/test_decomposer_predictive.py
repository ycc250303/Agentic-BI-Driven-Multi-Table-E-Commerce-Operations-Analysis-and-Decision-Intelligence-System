from __future__ import annotations

from agents.coordinator_agent.decomposer import (
    DecomposeResult,
    finalize_suggested_agents,
    normalize_predictive_sub_questions,
)


def test_normalize_gmv_predictive_to_single_historical_subquestion():
    subs = normalize_predictive_sub_questions(
        "根据历史订单趋势，预测未来 6 周的销售额，并给出趋势解读。",
        "predictive",
        ["预测未来6周的销售额", "获取历史月度GMV用于解读"],
    )
    assert len(subs) == 1
    assert "mv_monthly_sales" in subs[0]


def test_finalize_adds_visualization_for_gmv_predictive():
    result = DecomposeResult(
        intent="predictive",
        sub_questions=["预测未来6周销售额？"],
        suggested_agents=["data_analysis", "decision"],
        reasoning="llm",
    )
    out = finalize_suggested_agents(
        result, "根据历史订单趋势，预测未来 6 周的销售额，并给出趋势解读。"
    )
    assert "visualization" in out.suggested_agents
    assert len(out.sub_questions) == 1
