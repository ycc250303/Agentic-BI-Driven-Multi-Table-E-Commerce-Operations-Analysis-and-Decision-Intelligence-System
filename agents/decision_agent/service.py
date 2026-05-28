from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .llm import get_llm
from .prompt_builder import build_human_prompt, build_system_prompt
from .schemas import DecisionInputs, DecisionResult, RootCauseItem
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
    problem_types: list[str],
) -> tuple[str, dict[str, Any]]:
    query = inputs.user_query
    if "卖家" in query or "seller" in query.lower() or "seller" in problem_types:
        return "remove_top_bad_sellers", {"top_n": 20}
    if "配送" in query or "delivery" in query.lower() or "delivery" in problem_types:
        return "improve_delivery_days", {"improvement_days": 1.0}
    return "", {}


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


def run_decision(inputs: DecisionInputs, *, model=None) -> DecisionResult:
    llm = model or get_llm()
    state_like = inputs.model_dump(mode="python")

    bundle = build_evidence_bundle(state_like)
    problems = score_problems(bundle)
    action_plan = generate_action_plan(problems)

    scenario_type, parameters = choose_what_if(
        inputs, [problem.problem_type for problem in problems]
    )
    what_if_result = run_what_if(scenario_type, parameters, state_like)

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

    return decision_result


def answer_decision(
    *,
    user_query: str,
    analysis_result: dict[str, Any],
    nlp_result: dict[str, Any] | None = None,
    forecast_result: dict[str, Any] | None = None,
    visualization_result: dict[str, Any] | None = None,
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
        conversation_history=conversation_history or [],
    )
    result = run_decision(inputs, model=model)
    return result.narrative_answer
