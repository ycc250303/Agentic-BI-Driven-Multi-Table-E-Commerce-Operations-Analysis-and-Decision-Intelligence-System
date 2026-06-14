from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..llm import get_structured_llm
from ..schemas import DecisionInputs, EvidenceBundle, ScoredProblem, WhatIfPlan


_WHAT_IF_TERMS = (
    "如果",
    "假如",
    "假设",
    "模拟",
    "what-if",
    "what if",
    "会怎样",
    "会如何",
    "变化",
)


def has_what_if_intent(user_query: str, intent: str = "") -> bool:
    query = user_query.lower()
    if str(intent).lower() == "what_if":
        return True
    return any(term in query for term in _WHAT_IF_TERMS)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_prompt() -> str:
    return (
        _project_root() / "config" / "decision_agent" / "plan_what_if.md"
    ).read_text(encoding="utf-8")


def _structured_planner_model(model):
    if model is not None:
        return model.with_structured_output(WhatIfPlan)
    return get_structured_llm().with_structured_output(WhatIfPlan)


def _problem_payload(problems: list[ScoredProblem]) -> list[dict[str, Any]]:
    return [
        {
            "problem_type": item.problem_type,
            "problem": item.problem,
            "evidence": item.evidence,
            "priority_score": item.priority_score,
        }
        for item in problems[:3]
    ]


def _analysis_payload(inputs: DecisionInputs) -> dict[str, Any]:
    analysis = inputs.analysis_result or {}
    return {
        "summary_text": analysis.get("summary_text") or analysis.get("business_summary"),
        "kpis": analysis.get("kpis") or {},
        "findings": analysis.get("findings") or [],
        "simulation_inputs": analysis.get("simulation_inputs") or {},
        "key_rows": analysis.get("key_rows") or [],
    }


def _human_prompt(
    *,
    inputs: DecisionInputs,
    bundle: EvidenceBundle,
    problems: list[ScoredProblem],
) -> str:
    payload = {
        "user_query": inputs.user_query,
        "intent": inputs.intent,
        "analysis_result": _analysis_payload(inputs),
        "evidence_bundle": bundle.model_dump(mode="json"),
        "scored_problems": _problem_payload(problems),
    }
    return (
        "请将当前用户问题规划为通用 What-if 计划。"
        "只输出结构化结果，不要输出自然语言解释。\n\n"
        f"【输入】\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _fallback_plan(inputs: DecisionInputs, reason: str = "") -> WhatIfPlan:
    if not has_what_if_intent(inputs.user_query, inputs.intent):
        return WhatIfPlan(
            has_what_if_intent=False,
            question=inputs.user_query,
            reasoning_summary="用户本轮没有提出明确的 What-if 模拟问题。",
        )
    return WhatIfPlan(
        has_what_if_intent=True,
        plan_type="generic_what_if",
        question=inputs.user_query,
        target_metrics=[],
        computations=[],
        can_quantify=False,
        directional_only=True,
        missing_inputs=["what_if_plan.computations"],
        reasoning_summary=(
            "已识别为 What-if 问题，但结构化规划失败，无法安全生成定量模拟。"
        ),
        limitations=[reason] if reason else [],
    )


def plan_what_if(
    *,
    inputs: DecisionInputs,
    bundle: EvidenceBundle,
    problems: list[ScoredProblem],
    model=None,
) -> WhatIfPlan:
    if not has_what_if_intent(inputs.user_query, inputs.intent):
        return _fallback_plan(inputs)
    try:
        planner = _structured_planner_model(model)
        response = planner.invoke(
            [
                SystemMessage(content=_load_prompt()),
                HumanMessage(
                    content=_human_prompt(
                        inputs=inputs,
                        bundle=bundle,
                        problems=problems,
                    )
                ),
            ]
        )
        if isinstance(response, WhatIfPlan):
            return response
        return WhatIfPlan.model_validate(response)
    except Exception as exc:
        return _fallback_plan(inputs, reason=f"What-if 规划失败：{exc}")

