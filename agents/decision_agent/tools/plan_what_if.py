from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.common.llm import invoke_structured
from agents.common.prompts import compose_system_prompt

from ..schemas import DecisionInputs, EvidenceBundle, ScoredProblem, WhatIfPlan

logger = logging.getLogger(__name__)


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
    return WhatIfPlan(
        has_what_if_intent=False,
        plan_type="generic_what_if",
        question=inputs.user_query,
        target_metrics=[],
        computations=[],
        can_quantify=False,
        directional_only=False,
        missing_inputs=[],
        reasoning_summary=(
            "What-if 结构化规划失败，未运行模拟；系统未使用关键词规则推断意图。"
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
    try:
        response = invoke_structured(
            WhatIfPlan,
            [
                SystemMessage(content=compose_system_prompt("decision_agent", "plan_what_if.md")),
                HumanMessage(
                    content=_human_prompt(
                        inputs=inputs,
                        bundle=bundle,
                        problems=problems,
                    )
                ),
            ],
            model=model,
        )
        if isinstance(response, WhatIfPlan):
            return response
        return WhatIfPlan.model_validate(response)
    except Exception as exc:
        logger.warning("What-if 规划失败：%s", exc)
        return _fallback_plan(inputs, reason=f"What-if 规划失败：{exc}")

