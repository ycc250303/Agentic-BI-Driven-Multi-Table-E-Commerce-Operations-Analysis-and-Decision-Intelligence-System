"""协调器路由：强制完成 suggested_agents 全链路，避免过早 synthesize。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

AgentRoute = Literal["data_analysis", "visualization", "nlp", "decision", "synthesize"]

MAX_ORCHESTRATOR_ITERATIONS = 20

# SQL 完成后，其余 Agent 的推荐执行顺序（NLP 先于可视化，便于用评论洞察规划佐证图）
_POST_SQL_AGENT_ORDER: tuple[AgentRoute, ...] = ("nlp", "visualization", "decision")


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


def _suggested_agents(state: dict) -> list[str]:
    return list(state.get("suggested_agents") or [])


def _pending_post_sql_agents(state: dict) -> list[AgentRoute]:
    """suggested_agents 中尚未完成的后续 Agent（按推荐顺序）。"""
    suggested = set(_suggested_agents(state))
    pending: list[AgentRoute] = []
    for name in _POST_SQL_AGENT_ORDER:
        if name in suggested and not _agent_done(state, name):
            pending.append(name)
    return pending


def _should_visualize(state: dict) -> bool:
    if _agent_done(state, "visualization"):
        return False
    if _pending_sql_count(state) > 0:
        return False
    if not state.get("sql_runs"):
        return False
    if "visualization" in _suggested_agents(state):
        return True
    from agents.viz_agent.viz_planner import query_suggests_visualization

    return query_suggests_visualization(
        str(state.get("user_query") or ""),
        str(state.get("intent") or ""),
    )


def _should_nlp(state: dict) -> bool:
    from agents.nlp_agent.run import should_run_nlp

    return should_run_nlp(
        str(state.get("user_query") or ""),
        str(state.get("intent") or ""),
    )


def _should_decision(state: dict) -> bool:
    intent = str(state.get("intent") or "")
    query = str(state.get("user_query") or "")
    if intent in ("prescriptive", "what_if", "diagnostic"):
        return True
    if intent == "predictive":
        return any(k in query for k in ("建议", "策略", "方案", "如何", "怎么", "改进", "优化"))
    return False


def _enforce_suggested_pipeline(decision: RouteDecision, state: dict) -> RouteDecision:
    """LLM 若过早 synthesize，或 visualization 抢在 nlp 前，用规则纠正。"""
    if _pending_sql_count(state) > 0:
        if decision.next_agent != "data_analysis":
            return RouteDecision(
                next_agent="data_analysis",
                reasoning="仍有 sub_question 待查数，优先 data_analysis。",
            )
        return decision

    pending = _pending_post_sql_agents(state)
    if pending and decision.next_agent == "synthesize":
        nxt = pending[0]
        return RouteDecision(
            next_agent=nxt,
            reasoning=(
                f"分解阶段建议调度 {', '.join(_suggested_agents(state))}；"
                f"尚未完成 {nxt}，不得提前汇总。"
            ),
        )

    suggested = set(_suggested_agents(state))
    if (
        decision.next_agent == "visualization"
        and "nlp" in suggested
        and not _agent_done(state, "nlp")
    ):
        return RouteDecision(
            next_agent="nlp",
            reasoning="评论/差评类问题需先完成 NLP 洞察，再规划佐证图表。",
        )

    if decision.next_agent != "data_analysis" and _agent_done(state, decision.next_agent):
        return route_next_rule(state)

    return decision


def route_next_rule(state: dict) -> RouteDecision:
    pending = _pending_sql_count(state)
    if pending > 0:
        return RouteDecision(
            next_agent="data_analysis",
            reasoning=f"仍有 {pending} 个子问题待查数。",
        )

    post_pending = _pending_post_sql_agents(state)
    if post_pending:
        nxt = post_pending[0]
        return RouteDecision(
            next_agent=nxt,
            reasoning=f"按 suggested_agents 全链路执行，下一步：{nxt}。",
        )

    # suggested_agents 未列但语义仍需要的兜底（如分解器漏标）
    if not _agent_done(state, "nlp") and _should_nlp(state):
        return RouteDecision(next_agent="nlp", reasoning="问题涉及评论洞察，执行 NLP。")
    if not _agent_done(state, "visualization") and _should_visualize(state):
        return RouteDecision(
            next_agent="visualization",
            reasoning="问题适合可视化佐证，执行 visualization。",
        )
    if not _agent_done(state, "decision") and _should_decision(state):
        return RouteDecision(next_agent="decision", reasoning="诊断/决策类问题，执行 decision。")

    return RouteDecision(next_agent="synthesize", reasoning="全链路 Agent 已完成，生成最终回答。")


def _build_router_context(state: dict) -> str:
    done = state.get("agents_done") or {}
    sub_qs = state.get("sub_questions") or []
    sql_runs = state.get("sql_runs") or []
    pending = _pending_sql_count(state)
    post_pending = _pending_post_sql_agents(state)
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
            "suggested_agents": _suggested_agents(state),
            "pending_post_sql_agents": post_pending,
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
        return _enforce_suggested_pipeline(decision, state)
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
