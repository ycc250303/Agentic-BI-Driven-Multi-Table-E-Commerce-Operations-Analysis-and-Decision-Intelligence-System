from __future__ import annotations

import json
from pathlib import Path

from agents.decision_agent.schemas import DecisionInputs, WhatIfComputation, WhatIfPlan
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
    def __init__(self, what_if_plan: dict | None = None):
        self.what_if_plan = what_if_plan or WhatIfPlan(
            has_what_if_intent=False,
            question="",
        ).model_dump(mode="json")

    def with_structured_output(self, schema):
        if schema.__name__ == "WhatIfPlan":
            return DummyStructuredResponse(self.what_if_plan)
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


class FailingPlanModel(DummyModel):
    def with_structured_output(self, schema):
        if schema.__name__ == "WhatIfPlan":
            raise RuntimeError("planner unavailable")
        return super().with_structured_output(schema)


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
    assert result.what_if_result.status == "not_run"


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


def test_run_decision_runs_generic_quantified_what_if():
    state = load_case("category_risk.json")
    inputs = DecisionInputs(
        user_query="如果 GMV 基线 100 万、转化提升 10%，GMV 会怎样？",
        intent="what_if",
        analysis_result=state["analysis_result"],
        nlp_result=state.get("nlp_result") or {},
        forecast_result=state.get("forecast_result") or {},
        visualization_result=state.get("visualization_result") or {},
        conversation_history=state.get("conversation_history") or [],
    )
    plan = WhatIfPlan(
        has_what_if_intent=True,
        question=inputs.user_query,
        can_quantify=True,
        computations=[
            WhatIfComputation(
                target_metric="gmv",
                baseline_value=1_000_000,
                change_value=0.10,
                formula="percent_change",
                baseline_source="用户假设",
                change_source="用户假设",
            )
        ],
    )

    result = run_decision(inputs, model=DummyModel(plan.model_dump(mode="json")))

    assert result.what_if_result.scenario_type == "quantified_what_if"
    assert result.what_if_result.status == "run"
    assert result.what_if_result.simulated_metrics["gmv"] == 1_100_000


def test_run_decision_current_what_if_ignores_legacy_snapshot():
    state = load_case("category_risk.json")
    inputs = DecisionInputs(
        user_query="如果 GMV 基线 100 万、转化提升 10%，GMV 会怎样？",
        intent="what_if",
        analysis_result=state["analysis_result"],
        nlp_result=state.get("nlp_result") or {},
        forecast_result=state.get("forecast_result") or {},
        visualization_result=state.get("visualization_result") or {},
        what_if_result={
            "scenario_type": "remove_top_bad_sellers",
            "status": "run",
            "summary_text": "历史固定场景快照。",
        },
        conversation_history=state.get("conversation_history") or [],
    )
    plan = WhatIfPlan(
        has_what_if_intent=True,
        question=inputs.user_query,
        can_quantify=True,
        computations=[
            WhatIfComputation(
                target_metric="gmv",
                baseline_value=1_000_000,
                change_value=0.10,
                formula="percent_change",
                baseline_source="用户假设",
                change_source="用户假设",
            )
        ],
    )

    result = run_decision(inputs, model=DummyModel(plan.model_dump(mode="json")))

    assert result.what_if_result.scenario_type == "quantified_what_if"
    assert result.what_if_result.status == "run"
    assert result.what_if_result.summary_text != "历史固定场景快照。"


def test_run_decision_degrades_when_what_if_planner_fails():
    state = load_case("category_risk.json")
    inputs = DecisionInputs(
        user_query="如果加大 SP 州运营投入会怎样？",
        intent="what_if",
        analysis_result=state["analysis_result"],
        nlp_result=state.get("nlp_result") or {},
        forecast_result=state.get("forecast_result") or {},
        visualization_result=state.get("visualization_result") or {},
        conversation_history=state.get("conversation_history") or [],
    )

    result = run_decision(inputs, model=FailingPlanModel())

    assert result.what_if_result.status == "not_run"
    assert "规划失败" in result.what_if_result.summary_text
    assert result.what_if_result.baseline_metrics == {}
    assert result.what_if_result.simulated_metrics == {}


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
