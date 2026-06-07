from __future__ import annotations

from agents.decision_agent.schemas import DecisionInputs
from agents.decision_agent.warning_policy import collect_input_warnings


def _inputs(**kwargs) -> DecisionInputs:
    base = {
        "user_query": "",
        "intent": "descriptive",
        "analysis_result": {"summary_text": "ok"},
        "nlp_result": {},
        "forecast_result": {},
        "visualization_result": {"charts": []},
    }
    base.update(kwargs)
    return DecisionInputs(**base)


def test_no_nlp_warning_for_gmv_descriptive_query():
    warnings = collect_input_warnings(
        _inputs(
            user_query="2017 年 GMV 是多少？",
            intent="descriptive",
        )
    )
    assert "nlp_result" not in " ".join(warnings)


def test_forecast_warning_for_predictive_when_attempted_but_empty():
    warnings = collect_input_warnings(
        _inputs(
            user_query="预测未来各品类差评订单数变化趋势并给出风险预警",
            intent="predictive",
            forecast_result={},
        ),
        pipeline={"forecast_attempted": True, "suggested_agents": ["decision"]},
    )
    assert any("forecast_result" in w for w in warnings)


def test_no_forecast_warning_when_predictive_has_payload():
    warnings = collect_input_warnings(
        _inputs(
            user_query="预测未来各品类差评订单数变化趋势",
            intent="predictive",
            forecast_result={"summary_text": "识别出3个恶化品类", "trend_direction": "up"},
        ),
        pipeline={"forecast_attempted": True},
    )
    assert "forecast_result" not in " ".join(warnings)


def test_nlp_warning_when_review_query_missing_nlp():
    warnings = collect_input_warnings(
        _inputs(
            user_query="Top 10 差评品类及其主要差评原因是什么？",
            intent="diagnostic",
            nlp_result={},
        ),
        pipeline={"suggested_agents": ["nlp", "decision"]},
    )
    assert any("nlp_result" in w for w in warnings)
