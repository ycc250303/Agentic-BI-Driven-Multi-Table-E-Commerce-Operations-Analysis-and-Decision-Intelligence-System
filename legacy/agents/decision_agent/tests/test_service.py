from __future__ import annotations

import json
from pathlib import Path

from agents.decision_agent.schemas import DecisionInputs, WhatIfComputation, WhatIfPlan
from agents.decision_agent.service import answer_decision, run_decision


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_case(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _inputs_from_case(name: str, **overrides) -> DecisionInputs:
    state = load_case(name)
    payload = {
        "user_query": state["user_query"],
        "intent": state.get("intent") or "prescriptive",
        "analysis_result": state["analysis_result"],
        "nlp_result": state.get("nlp_result") or {},
        "forecast_result": state.get("forecast_result") or {},
        "visualization_result": state.get("visualization_result") or {},
        "conversation_history": state.get("conversation_history") or [],
    }
    payload.update(overrides)
    return DecisionInputs(**payload)


def test_run_decision_returns_structured_result(stub_decision_llm):
    stub_decision_llm()
    result = run_decision(_inputs_from_case("high_delivery_risk.json"))
    assert result.narrative_answer
    assert result.action_plan
    assert result.what_if_result.status == "not_run"


def test_run_decision_falls_back_when_narrative_llm_fails(stub_decision_llm):
    stub_decision_llm(empty_narrative=True)
    result = run_decision(_inputs_from_case("high_delivery_risk.json"))

    assert result.narrative_answer
    assert result.action_plan
    assert "规则层确定性摘要生成" in " ".join(result.assumptions)
    assert any("叙述层生成失败" in issue for issue in result.quality_report["issues"])


def test_run_decision_runs_generic_quantified_what_if(stub_decision_llm):
    inputs = _inputs_from_case(
        "category_risk.json",
        user_query="如果 GMV 基线 100 万、转化提升 10%，GMV 会怎样？",
        intent="what_if",
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
    stub_decision_llm(plan=plan.model_dump(mode="json"))

    result = run_decision(inputs)

    assert result.what_if_result.scenario_type == "quantified_what_if"
    assert result.what_if_result.status == "run"
    assert result.what_if_result.simulated_metrics["gmv"] == 1_100_000


def test_run_decision_current_what_if_ignores_legacy_snapshot(stub_decision_llm):
    inputs = _inputs_from_case(
        "category_risk.json",
        user_query="如果 GMV 基线 100 万、转化提升 10%，GMV 会怎样？",
        intent="what_if",
        what_if_result={
            "scenario_type": "remove_top_bad_sellers",
            "status": "run",
            "summary_text": "历史固定场景快照。",
        },
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
    stub_decision_llm(plan=plan.model_dump(mode="json"))

    result = run_decision(inputs)

    assert result.what_if_result.scenario_type == "quantified_what_if"
    assert result.what_if_result.status == "run"
    assert result.what_if_result.summary_text != "历史固定场景快照。"


def test_run_decision_degrades_when_what_if_planner_fails(stub_decision_llm):
    stub_decision_llm(fail_plan=True)
    result = run_decision(
        _inputs_from_case(
            "category_risk.json",
            user_query="如果加大 SP 州运营投入会怎样？",
            intent="what_if",
        )
    )

    assert result.what_if_result.status == "not_run"
    assert "规划失败" in result.what_if_result.summary_text
    assert result.what_if_result.baseline_metrics == {}
    assert result.what_if_result.simulated_metrics == {}


def test_answer_decision_returns_string(stub_decision_llm):
    stub_decision_llm()
    state = load_case("high_delivery_risk.json")
    answer = answer_decision(
        user_query=state["user_query"],
        intent=state.get("intent") or "prescriptive",
        analysis_result=state["analysis_result"],
        nlp_result=state.get("nlp_result") or {},
        forecast_result=state.get("forecast_result") or {},
        visualization_result=state.get("visualization_result") or {},
        conversation_history=state.get("conversation_history") or [],
    )
    assert isinstance(answer, str)
    assert answer
