from __future__ import annotations

import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .adapters import (
    normalize_analysis_result,
    normalize_forecast_result,
    normalize_nlp_result,
    normalize_visualization_result,
    normalize_what_if_result,
)
from .llm import get_llm
from .prompt_builder import build_human_prompt, build_system_prompt
from .quality import evaluate_decision_quality, quality_report_to_dict
from .schemas import DecisionInputs, DecisionResult, RootCauseItem, ScoredProblem, WhatIfResult
from .tools import (
    build_evidence_bundle,
    generate_action_plan,
    run_what_if,
    score_problems,
)


class NarrativeResponse(BaseModel):
    narrative_answer: str = Field(description="面向用户展示的业务建议总结")
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


WHAT_IF_SCENARIOS: dict[str, dict[str, Any]] = {
    "remove_top_bad_sellers": {
        "problem_type": "seller",
        "default_parameters": {"top_n": 20},
    },
    "improve_delivery_days": {
        "problem_type": "delivery",
        "default_parameters": {"improvement_days": 1.0},
    },
}

_EXPLICIT_WHAT_IF_TERMS = (
    "如果",
    "假如",
    "模拟",
    "what-if",
    "what if",
    "会怎样",
    "变化",
    "干预",
    "提升",
    "降低",
    "减少",
    "缩短",
    "下架",
    "剔除",
)


def _normalize_inputs(inputs: DecisionInputs) -> DecisionInputs:
    data = inputs.model_dump(mode="python")
    return DecisionInputs(
        user_query=inputs.user_query,
        intent=inputs.intent,
        analysis_result=normalize_analysis_result(data.get("analysis_result")),
        nlp_result=normalize_nlp_result(data.get("nlp_result")),
        forecast_result=normalize_forecast_result(data.get("forecast_result")),
        visualization_result=normalize_visualization_result(data.get("visualization_result")),
        what_if_result=normalize_what_if_result(data.get("what_if_result")),
        conversation_history=inputs.conversation_history,
    )


def collect_input_warnings(inputs: DecisionInputs) -> list[str]:
    warnings: list[str] = []
    if not inputs.analysis_result:
        warnings.append("缺少 analysis_result，Decision-Agent 无法完成核心证据整理。")
    if not inputs.nlp_result:
        warnings.append("缺少 nlp_result，将无法充分解释评论与情绪相关根因。")
    if not inputs.forecast_result:
        warnings.append("缺少 forecast_result，将无法给出预测驱动的增长风险解释。")
    if not inputs.visualization_result:
        warnings.append("缺少 visualization_result，本次建议不会引用图表结论。")
    return warnings


def choose_what_if(
    inputs: DecisionInputs,
    problems: list[ScoredProblem],
) -> tuple[str, dict[str, Any]]:
    query = inputs.user_query.lower()
    explicit = any(term in query for term in _EXPLICIT_WHAT_IF_TERMS)

    if explicit:
        for scenario_type, spec in WHAT_IF_SCENARIOS.items():
            problem_type = spec["problem_type"]
            if problem_type in query:
                return scenario_type, dict(spec["default_parameters"])
        if "卖家" in query:
            return "remove_top_bad_sellers", {"top_n": 20}
        if "配送" in query or "物流" in query:
            return "improve_delivery_days", {"improvement_days": 1.0}

    if not problems:
        return "", {}

    top_problem_type = problems[0].problem_type
    for scenario_type, spec in WHAT_IF_SCENARIOS.items():
        if spec["problem_type"] == top_problem_type:
            return scenario_type, dict(spec["default_parameters"])
    return "", {}


def _coerce_existing_what_if(raw: dict[str, Any]) -> WhatIfResult:
    result = WhatIfResult.model_validate(raw)
    if result.status == "not_run" and (
        result.summary_text or result.baseline_metrics or result.simulated_metrics
    ):
        result.status = "run"
    if result.status == "run" and not result.limitations:
        result.limitations = ["沿用上游 What-if 结果；其可靠性取决于上游模拟口径。"]
    return result


def _select_what_if_result(
    inputs: DecisionInputs,
    problems: list[ScoredProblem],
    state_like: dict[str, Any],
) -> WhatIfResult:
    if inputs.what_if_result:
        return _coerce_existing_what_if(inputs.what_if_result)
    scenario_type, parameters = choose_what_if(inputs, problems)
    return run_what_if(scenario_type, parameters, state_like)


def compose_final_answer(
    *,
    model,
    bundle,
    problems,
    decision_result: DecisionResult,
) -> NarrativeResponse:
    structured_model = model.with_structured_output(NarrativeResponse)
    messages = [
        SystemMessage(content=build_system_prompt()),
        HumanMessage(
            content=build_human_prompt(
                bundle=bundle,
                scored_problems=problems,
                structured_result=decision_result,
            )
        ),
    ]
    response = structured_model.invoke(messages)
    if isinstance(response, NarrativeResponse):
        return response
    if isinstance(response, dict):
        return NarrativeResponse.model_validate(response)
    return NarrativeResponse.model_validate(response)


def revise_final_answer(
    *,
    model,
    bundle,
    problems,
    decision_result: DecisionResult,
    issues: list[str],
) -> NarrativeResponse:
    structured_model = model.with_structured_output(NarrativeResponse)
    messages = [
        SystemMessage(content=build_system_prompt()),
        HumanMessage(
            content="\n\n".join(
                [
                    "请只基于已有证据修订最终业务建议，不得新增输入中不存在的事实或数值。",
                    "需要修订的问题：",
                    "\n".join(f"- {issue}" for issue in issues) or "- 无",
                    "请保持回答简洁，并在证据不足或 What-if 未运行时明确说明边界。",
                    build_human_prompt(
                        bundle=bundle,
                        scored_problems=problems,
                        structured_result=decision_result,
                    ),
                ]
            )
        ),
    ]
    response = structured_model.invoke(messages)
    if isinstance(response, NarrativeResponse):
        return response
    if isinstance(response, dict):
        return NarrativeResponse.model_validate(response)
    return NarrativeResponse.model_validate(response)


def run_decision(inputs: DecisionInputs, *, model=None) -> DecisionResult:
    inputs = _normalize_inputs(inputs)
    llm = model or get_llm()
    state_like = inputs.model_dump(mode="python")

    bundle = build_evidence_bundle(state_like)
    problems = score_problems(bundle)
    action_plan = generate_action_plan(problems)

    what_if_result = _select_what_if_result(inputs, problems, state_like)

    root_causes = [
        RootCauseItem(
            cause=cause,
            supporting_evidence=problem.evidence[:2] or ["未提供直接证据"],
        )
        for problem in problems[:3]
        for cause in problem.root_cause_candidates[:2]
    ]

    decision_result = DecisionResult(
        decision_theme=problems[0].decision_theme,
        problem_statement=problems[0].problem,
        key_findings=[
            {
                "problem": problem.problem,
                "evidence": problem.evidence,
                "severity": problem.severity,
                "priority_score": problem.priority_score,
            }
            for problem in problems[:3]
        ],
        root_causes=root_causes,
        action_plan=action_plan,
        what_if_result=what_if_result,
        risks=[
            "部分建议依赖上游指标口径稳定，若口径调整需同步校准阈值。",
            "What-if 结果仅对当前输入快照负责，不代表未来实时经营结果。",
        ],
        assumptions=[
            "上游 analysis_result、nlp_result、forecast_result 已完成标准化。",
            "当前建议不直接访问原始业务表，所有推断均基于共享 state 输入。",
        ],
    )

    narrative = compose_final_answer(
        model=llm,
        bundle=bundle,
        problems=problems,
        decision_result=decision_result,
    )
    decision_result.narrative_answer = narrative.narrative_answer
    if narrative.risks:
        decision_result.risks = narrative.risks
    if narrative.assumptions:
        decision_result.assumptions = narrative.assumptions

    report = evaluate_decision_quality(bundle=bundle, decision_result=decision_result)
    max_revisions = int(os.getenv("DECISION_AGENT_MAX_REVISIONS", "1") or "0")
    review_mode = os.getenv("DECISION_AGENT_REVIEW_MODE", "deterministic").lower()
    if (
        review_mode != "off"
        and report.needs_revision
        and max_revisions > 0
    ):
        try:
            revised = revise_final_answer(
                model=llm,
                bundle=bundle,
                problems=problems,
                decision_result=decision_result,
                issues=report.issues,
            )
            decision_result.narrative_answer = revised.narrative_answer
            if revised.risks:
                decision_result.risks = revised.risks
            if revised.assumptions:
                decision_result.assumptions = revised.assumptions
            decision_result.revision_count = 1
            report = evaluate_decision_quality(
                bundle=bundle,
                decision_result=decision_result,
            )
        except Exception as exc:  # pragma: no cover - defensive LLM fallback
            report.issues.append(f"质量修订失败，保留第一版回答：{exc}")
    decision_result.quality_report = quality_report_to_dict(report)

    return decision_result


def answer_decision(
    *,
    user_query: str,
    analysis_result: dict[str, Any],
    nlp_result: dict[str, Any] | None = None,
    forecast_result: dict[str, Any] | None = None,
    visualization_result: dict[str, Any] | None = None,
    what_if_result: dict[str, Any] | None = None,
    intent: str = "prescriptive",
    conversation_history: list[dict[str, str]] | None = None,
    model=None,
) -> str:
    inputs = DecisionInputs(
        user_query=user_query,
        intent=intent,
        analysis_result=analysis_result,
        nlp_result=nlp_result or {},
        forecast_result=forecast_result or {},
        visualization_result=visualization_result or {},
        what_if_result=what_if_result or {},
        conversation_history=conversation_history or [],
    )
    result = run_decision(inputs, model=model)
    return result.narrative_answer
