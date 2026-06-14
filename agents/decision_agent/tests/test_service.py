from __future__ import annotations

import json
from pathlib import Path

from agents.decision_agent.schemas import DecisionInputs
from agents.decision_agent.service import answer_decision, run_decision


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_case(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class DummyStructuredResponse:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, messages):
        return self.payload


class DummyModel:
    def with_structured_output(self, schema):
        return DummyStructuredResponse(
            {
                "narrative_answer": "根据证据，建议优先治理配送延迟与高负面区域。",
                "risks": ["测试模式下未接入真实 API"],
                "assumptions": ["使用 fixture 数据进行验证"],
            }
        )


class EmptyResponseModel:
    def with_structured_output(self, schema):
        return DummyStructuredResponse(None)


def test_run_decision_returns_structured_result():
    state = load_case("high_delivery_risk.json")
    inputs = DecisionInputs(
        user_query=state["user_query"],
        intent=state.get("intent") or "prescriptive",
        analysis_result=state["analysis_result"],
        nlp_result=state.get("nlp_result") or {},
        forecast_result=state.get("forecast_result") or {},
        visualization_result=state.get("visualization_result") or {},
        conversation_history=state.get("conversation_history") or [],
    )
    result = run_decision(inputs, model=DummyModel())
    assert result.narrative_answer
    assert result.action_plan
    assert result.what_if_result.scenario_type == "improve_delivery_days"


def test_run_decision_falls_back_when_narrative_llm_fails():
    state = load_case("high_delivery_risk.json")
    inputs = DecisionInputs(
        user_query=state["user_query"],
        intent=state.get("intent") or "prescriptive",
        analysis_result=state["analysis_result"],
        nlp_result=state.get("nlp_result") or {},
        forecast_result=state.get("forecast_result") or {},
        visualization_result=state.get("visualization_result") or {},
        conversation_history=state.get("conversation_history") or [],
    )

    result = run_decision(inputs, model=EmptyResponseModel())

    assert result.narrative_answer
    assert result.action_plan
    assert "规则层确定性摘要生成" in " ".join(result.assumptions)
    assert any("叙述层生成失败" in issue for issue in result.quality_report["issues"])


def test_run_decision_selects_category_quality_what_if():
    state = load_case("category_risk.json")
    state["analysis_result"]["simulation_inputs"] = {
        "category_quality_impact": {
            "category": "bed_bath_table",
            "baseline_negative_rate": 0.31,
            "improved_negative_rate": 0.24,
            "baseline_bad_review_count": 240,
            "improved_bad_review_count": 176,
        }
    }
    inputs = DecisionInputs(
        user_query=state["user_query"],
        intent=state.get("intent") or "prescriptive",
        analysis_result=state["analysis_result"],
        nlp_result=state.get("nlp_result") or {},
        forecast_result=state.get("forecast_result") or {},
        visualization_result=state.get("visualization_result") or {},
        conversation_history=state.get("conversation_history") or [],
    )

    result = run_decision(inputs, model=DummyModel())

    assert result.what_if_result.scenario_type == "improve_category_quality"
    assert result.what_if_result.status == "run"


def test_answer_decision_returns_string():
    state = load_case("high_delivery_risk.json")
    answer = answer_decision(
        user_query=state["user_query"],
        intent=state.get("intent") or "prescriptive",
        analysis_result=state["analysis_result"],
        nlp_result=state.get("nlp_result") or {},
        forecast_result=state.get("forecast_result") or {},
        visualization_result=state.get("visualization_result") or {},
        conversation_history=state.get("conversation_history") or [],
        model=DummyModel(),
    )
    assert isinstance(answer, str)
    assert answer
