from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

AgentRoute = Literal["data_analysis", "visualization", "nlp", "decision", "synthesize"]

MAX_ORCHESTRATOR_ITERATIONS = 20


class RouteDecision(BaseModel):
    next_agent: AgentRoute
    reasoning: str = ""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_prompt() -> str:
    return (_project_root() / "config" / "coordinator_agent" / "route_next.md").read_text(
        encoding="utf-8"
    )


def _extract_json_object(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _pending_sql_count(state: dict) -> int:
    sub_qs = state.get("sub_questions") or []
    done = len(state.get("sql_runs") or [])
    return max(0, len(sub_qs) - done)


def _agent_done(state: dict, name: str) -> bool:
    return bool((state.get("agents_done") or {}).get(name))


def _should_visualize(state: dict) -> bool:
    if not state.get("sql_runs"):
        return False
    intent = str(state.get("intent") or "")
    if intent in ("prescriptive", "what_if"):
        return True
    query = str(state.get("user_query") or "")
    hints = ("趋势", "排名", "对比", "分布", "各州", "各月", "top", "最高", "最低")
    return any(h in query.lower() or h in query for h in hints)


def _should_nlp(state: dict) -> bool:
    from agents.nlp_agent.run import should_run_nlp

    return should_run_nlp(
        str(state.get("user_query") or ""),
        str(state.get("intent") or ""),
    )


def _should_decision(state: dict) -> bool:
    intent = str(state.get("intent") or "")
    if intent in ("prescriptive", "what_if"):
        return True
    if intent in ("diagnostic", "predictive"):
        query = str(state.get("user_query") or "")
        return any(k in query for k in ("建议", "策略", "方案", "如何", "怎么", "改进", "优化"))
    return False


def route_next_rule(state: dict) -> RouteDecision:
    pending = _pending_sql_count(state)
    if pending > 0:
        return RouteDecision(
            next_agent="data_analysis",
            reasoning=f"仍有 {pending} 个子问题待查数。",
        )

    if not _agent_done(state, "visualization") and _should_visualize(state):
        return RouteDecision(
            next_agent="visualization",
            reasoning="SQL 结果适合可视化且尚未出图。",
        )

    if not _agent_done(state, "nlp") and _should_nlp(state):
        return RouteDecision(
            next_agent="nlp",
            reasoning="问题涉及评论/诊断/决策，需评论洞察。",
        )

    if not _agent_done(state, "decision") and _should_decision(state):
        return RouteDecision(
            next_agent="decision",
            reasoning="用户需要策略/建议类输出。",
        )

    return RouteDecision(next_agent="synthesize", reasoning="证据已足够，生成最终回答。")


def _build_router_context(state: dict) -> str:
    done = state.get("agents_done") or {}
    sub_qs = state.get("sub_questions") or []
    sql_runs = state.get("sql_runs") or []
    pending = _pending_sql_count(state)
    log = state.get("execution_log") or []
    recent = log[-6:] if log else []
    return json.dumps(
        {
            "user_query": state.get("user_query"),
            "intent": state.get("intent"),
            "sub_questions": sub_qs,
            "sql_completed": len(sql_runs),
            "sql_pending": pending,
            "agents_done": done,
            "suggested_agents": state.get("suggested_agents") or [],
            "recent_execution_log": recent,
        },
        ensure_ascii=False,
        indent=2,
    )


def route_next_llm(state: dict, *, model=None) -> RouteDecision:
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.decision_agent.llm import get_llm

    llm = model or get_llm()
    system = _load_prompt()
    human = f"【当前状态】\n{_build_router_context(state)}\n\n请输出 JSON。"
    try:
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
        raw = _extract_json_object(str(resp.content))
        decision = RouteDecision.model_validate_json(raw)
        if decision.next_agent == "data_analysis" and _pending_sql_count(state) == 0:
            return route_next_rule(state)
        if decision.next_agent != "data_analysis" and _agent_done(state, decision.next_agent):
            return route_next_rule(state)
        return decision
    except Exception:
        return route_next_rule(state)


def choose_next_agent(state: dict, *, use_llm: bool = True, model=None) -> RouteDecision:
    iterations = int(state.get("orchestrator_iterations") or 0)
    if iterations >= MAX_ORCHESTRATOR_ITERATIONS:
        return RouteDecision(
            next_agent="synthesize",
            reasoning=f"已达最大迭代次数 {MAX_ORCHESTRATOR_ITERATIONS}，强制汇总。",
        )
    if use_llm:
        return route_next_llm(state, model=model)
    return route_next_rule(state)
