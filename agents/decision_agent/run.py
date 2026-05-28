from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .llm import get_llm
from .prompt_builder import build_human_prompt, build_system_prompt
from .schemas import DecisionResult, RootCauseItem
from .state import BIState
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


class DecisionAgent:
    def __init__(self, model=None):
        self.model = model or get_llm()

    @staticmethod
    def validate_inputs(state: BIState) -> list[str]:
        warnings = list(state.get("warnings") or [])
        if not state.get("analysis_result"):
            warnings.append("缺少 analysis_result，Decision-Agent 无法完成核心证据整理。")
        if not state.get("nlp_result"):
            warnings.append("缺少 nlp_result，将无法充分解释评论与情绪相关根因。")
        if not state.get("forecast_result"):
            warnings.append("缺少 forecast_result，将无法给出预测驱动的增长风险解释。")
        if not state.get("visualization_result"):
            warnings.append("缺少 visualization_result，本次建议不会引用图表结论。")
        return warnings

    @staticmethod
    def _choose_what_if(state: BIState, problem_types: list[str]) -> tuple[str, dict[str, Any]]:
        query = str(state.get("user_query") or "")
        if "卖家" in query or "seller" in query.lower() or "seller" in problem_types:
            return "remove_top_bad_sellers", {"top_n": 20}
        if "配送" in query or "delivery" in query.lower() or "delivery" in problem_types:
            return "improve_delivery_days", {"improvement_days": 1.0}
        return "", {}

    def compose_final_answer(
        self,
        *,
        bundle,
        problems,
        decision_result: DecisionResult,
    ) -> NarrativeResponse:
        structured_model = self.model.with_structured_output(NarrativeResponse)
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

    def run(self, state: BIState) -> BIState:
        next_state = dict(state)
        warnings = self.validate_inputs(next_state)
        next_state["warnings"] = warnings

        bundle = build_evidence_bundle(next_state)
        problems = score_problems(bundle)
        action_plan = generate_action_plan(problems)

        scenario_type, parameters = self._choose_what_if(
            next_state, [problem.problem_type for problem in problems]
        )
        what_if_result = run_what_if(scenario_type, parameters, next_state)

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

        narrative = self.compose_final_answer(
            bundle=bundle,
            problems=problems,
            decision_result=decision_result,
        )
        decision_result.narrative_answer = narrative.narrative_answer
        if narrative.risks:
            decision_result.risks = narrative.risks
        if narrative.assumptions:
            decision_result.assumptions = narrative.assumptions

        next_state["decision_result"] = decision_result.model_dump(mode="json")
        next_state["final_answer"] = decision_result.narrative_answer
        return next_state


def decision_node(state: BIState) -> BIState:
    return DecisionAgent().run(state)


def _load_fixture(path: str) -> BIState:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("fixture 内容必须是 JSON object。")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Run decision agent with a fixture state.")
    parser.add_argument("--fixture", required=True, help="Path to fixture JSON.")
    args = parser.parse_args()
    state = _load_fixture(args.fixture)
    result = decision_node(state)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
