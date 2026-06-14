from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field


MAX_REPLAN_COUNT = 1


class ReplanDecision(BaseModel):
    should_replan: bool = False
    evidence_status: str = "sufficient"
    sub_questions: list[str] = Field(default_factory=list)
    suggested_agents: list[str] = Field(default_factory=list)
    reason: str = ""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_prompt() -> str:
    return (
        _project_root() / "config" / "coordinator_agent" / "replan_query.md"
    ).read_text(encoding="utf-8")


def _extract_json_object(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _what_if_result(state: dict[str, Any]) -> dict[str, Any]:
    decision = state.get("decision_result") or {}
    return decision.get("what_if_result") or state.get("what_if_result") or {}


def _decision_missing_inputs(state: dict[str, Any]) -> list[str]:
    what_if = _what_if_result(state)
    status = str(what_if.get("status") or "")
    if status not in {"missing_inputs", "directional_only"}:
        return []
    return [str(item) for item in (what_if.get("missing_inputs") or []) if str(item)]


def _sql_result_is_empty_or_failed(run: dict[str, Any]) -> bool:
    pipeline = run.get("sql_pipeline") or {}
    raw = run.get("execute_sql_json") or pipeline.get("execute_sql_json") or ""
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}
    if payload and not payload.get("ok"):
        return True
    results = payload.get("results") or []
    if results:
        return sum(int(item.get("row_count_returned") or 0) for item in results) == 0
    analysis = run.get("analysis_result") or {}
    tables = analysis.get("tables") or []
    if tables:
        return sum(int(item.get("row_count") or 0) for item in tables) == 0
    return False


def _has_empty_or_weak_evidence(state: dict[str, Any]) -> bool:
    runs = state.get("sql_runs") or []
    if not runs:
        return False
    if any(_sql_result_is_empty_or_failed(run) for run in runs):
        return True
    analysis = state.get("analysis_result") or {}
    return not bool(analysis.get("key_rows"))


def inspect_agent_outputs(state: dict[str, Any]) -> tuple[str, str]:
    if _decision_missing_inputs(state):
        return "missing_inputs", "Decision Agent 的 What-if 结果缺少可验证输入。"
    if _has_empty_or_weak_evidence(state):
        return "empty_or_weak", "数据分析结果为空、失败或证据行不足。"
    return "sufficient", ""


def _replan_context(state: dict[str, Any]) -> dict[str, Any]:
    what_if = _what_if_result(state)
    sql_summaries: list[dict[str, Any]] = []
    for run in state.get("sql_runs") or []:
        analysis = run.get("analysis_result") or {}
        sql_summaries.append(
            {
                "question": run.get("question"),
                "summary_text": analysis.get("summary_text") or analysis.get("business_summary"),
                "key_rows_count": len(analysis.get("key_rows") or []),
                "tables": [
                    {
                        "row_count": table.get("row_count"),
                        "ok": table.get("ok"),
                    }
                    for table in (analysis.get("tables") or [])
                ],
            }
        )
    return {
        "user_query": state.get("user_query"),
        "intent": state.get("intent"),
        "current_sub_questions": state.get("sub_questions") or [],
        "suggested_agents": state.get("suggested_agents") or [],
        "what_if_status": what_if.get("status"),
        "missing_inputs": what_if.get("missing_inputs") or [],
        "what_if_summary": what_if.get("summary_text"),
        "sql_summaries": sql_summaries,
        "replan_count": int(state.get("replan_count") or 0),
    }


def _structured_replanner_model(model):
    if model is not None:
        return model.with_structured_output(ReplanDecision)
    from agents.decision_agent.llm import get_structured_llm

    return get_structured_llm().with_structured_output(ReplanDecision)


def plan_recovery_queries(state: dict[str, Any], *, model=None) -> ReplanDecision:
    status, reason = inspect_agent_outputs(state)
    if status == "sufficient":
        return ReplanDecision(should_replan=False, evidence_status=status, reason=reason)
    if int(state.get("replan_count") or 0) >= MAX_REPLAN_COUNT:
        return ReplanDecision(should_replan=False, evidence_status=status, reason=reason)
    try:
        replanner = _structured_replanner_model(model)
        response = replanner.invoke(
            [
                SystemMessage(content=_load_prompt()),
                HumanMessage(
                    content=(
                        "请审查当前状态，判断是否需要补充数据分析。\n\n"
                        f"【当前状态】\n{json.dumps(_replan_context(state), ensure_ascii=False, indent=2)}"
                    )
                ),
            ]
        )
        decision = (
            response if isinstance(response, ReplanDecision)
            else ReplanDecision.model_validate(response)
        )
        if not decision.evidence_status:
            decision.evidence_status = status
        if not decision.reason:
            decision.reason = reason
        return decision
    except Exception as exc:
        return ReplanDecision(
            should_replan=False,
            evidence_status=status,
            reason=f"{reason} Replan 规划失败：{exc}",
        )


def apply_replan_decision(state: dict[str, Any], decision: ReplanDecision) -> dict[str, Any]:
    patch: dict[str, Any] = {
        "evidence_status": decision.evidence_status,
        "replan_reason": decision.reason,
    }
    if not decision.should_replan or not decision.sub_questions:
        return patch

    agents = list(decision.suggested_agents or ["data_analysis", "decision"])
    if "data_analysis" not in agents:
        agents.insert(0, "data_analysis")
    if "decision" not in agents:
        agents.append("decision")
    done = dict(state.get("agents_done") or {})
    done.pop("data_analysis", None)
    done.pop("decision", None)
    patch.update(
        {
            "sub_questions": list(decision.sub_questions),
            "suggested_agents": agents,
            "sql_runs": [],
            "analysis_result": {},
            "decision_result": {},
            "what_if_result": {},
            "agents_done": done,
            "replan_count": int(state.get("replan_count") or 0) + 1,
        }
    )
    return patch
