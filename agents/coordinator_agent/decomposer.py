from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from agents.coordinator_agent.planner import IntentName, classify_intent


class DecomposeResult(BaseModel):
    intent: IntentName = "descriptive"
    sub_questions: list[str] = Field(min_length=1)
    suggested_agents: list[str] = Field(default_factory=list)
    reasoning: str = ""

    @field_validator("sub_questions")
    @classmethod
    def _strip_questions(cls, items: list[str]) -> list[str]:
        out = [str(q).strip() for q in items if str(q).strip()]
        if not out:
            raise ValueError("sub_questions 不能为空")
        return out


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_prompt(name: str) -> str:
    return (_project_root() / "config" / "coordinator_agent" / name).read_text(
        encoding="utf-8"
    )


def _extract_json_object(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _split_compound_query(user_query: str) -> list[str]:
    """规则拆分：按问号、分号及常见并列连词切分。"""
    text = user_query.strip()
    if not text:
        return []

    parts = re.split(r"[？?；;]+", text)
    chunks: list[str] = []
    for part in parts:
        p = part.strip().strip("，,")
        if not p:
            continue
        sub = re.split(r"(?:，|,|\s+以及\s+|\s+并且\s+|\s+同时\s+)", p)
        for s in sub:
            s = s.strip().strip("，,")
            if not s:
                continue
            if not s.endswith(("？", "?")):
                s = s + "？"
            chunks.append(s)

    if not chunks:
        q = text if text.endswith(("？", "?")) else text + "？"
        return [q]

    seen: set[str] = set()
    unique: list[str] = []
    for c in chunks:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _default_suggested_agents(intent: IntentName, user_query: str) -> list[str]:
    from agents.nlp_agent.run import should_run_nlp

    agents = ["data_analysis"]
    agents.append("visualization")
    if should_run_nlp(user_query, intent):
        agents.append("nlp")
    if intent in ("prescriptive", "what_if", "diagnostic", "predictive"):
        agents.append("decision")
    return agents


def decompose_query_rule(user_query: str) -> DecomposeResult:
    intent = classify_intent(user_query)
    sub_questions = _split_compound_query(user_query)
    if len(sub_questions) == 1 and sub_questions[0].rstrip("？?") == user_query.rstrip("？?"):
        sub_questions = [user_query if user_query.endswith(("？", "?")) else user_query + "？"]
    suggested = _default_suggested_agents(intent, user_query)
    reasoning = (
        f"规则拆分：intent={intent}，共 {len(sub_questions)} 个单问题，"
        f"建议 Agent：{', '.join(suggested)}。"
    )
    return DecomposeResult(
        intent=intent,
        sub_questions=sub_questions,
        suggested_agents=suggested,
        reasoning=reasoning,
    )


def decompose_query_llm(user_query: str, *, model=None) -> DecomposeResult:
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.decision_agent.llm import get_llm

    llm = model or get_llm()
    system = _load_prompt("decompose_query.md")
    human = f"【用户问题】\n{user_query}\n\n请输出 JSON。"
    try:
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
        raw = _extract_json_object(str(resp.content))
        result = DecomposeResult.model_validate_json(raw)
        if len(result.sub_questions) == 1:
            only = result.sub_questions[0]
            if only.rstrip("？?") == user_query.rstrip("？?"):
                return result
        return result
    except Exception:
        return decompose_query_rule(user_query)


def decompose_query(user_query: str, *, use_llm: bool = True, model=None) -> DecomposeResult:
    if use_llm:
        return decompose_query_llm(user_query, model=model)
    return decompose_query_rule(user_query)


def decompose_to_state_patch(user_query: str, result: DecomposeResult) -> dict:
    task_plan = [
        f"子问题 {i + 1}：{q}" for i, q in enumerate(result.sub_questions)
    ]
    task_plan.append(f"建议调度：{' → '.join(result.suggested_agents)} → 汇总回答")
    return {
        "user_query": user_query,
        "question": user_query,
        "intent": result.intent,
        "sub_questions": result.sub_questions,
        "suggested_agents": result.suggested_agents,
        "plan_reasoning": result.reasoning,
        "task_plan": task_plan,
        "sql_runs": [],
        "agents_done": {},
        "execution_log": [],
        "orchestrator_iterations": 0,
    }


def dump_decompose_json(result: DecomposeResult) -> str:
    return json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
