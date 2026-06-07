from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


DEFAULT_RECENT_TURNS = 3
SUMMARY_LIMIT = 1600
ANSWER_SNIPPET_LIMIT = 500


class SessionMemorySummary(BaseModel):
    memory_summary: str = Field(default="")
    updated_focus: str = Field(default="")

    @field_validator("memory_summary", "updated_focus")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return str(value or "").strip()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_summary_prompt() -> str:
    return (_project_root() / "config" / "coordinator_agent" / "summarize_session_memory.md").read_text(
        encoding="utf-8"
    )


def _clip(text: str, limit: int) -> str:
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "...(truncated)"


def build_conversation_history(
    session: dict[str, Any],
    *,
    recent_turns: int = DEFAULT_RECENT_TURNS,
) -> list[dict[str, str]]:
    """Build a compact chat history for the next coordinator turn."""
    history: list[dict[str, str]] = []
    summary = str(session.get("memory_summary") or "").strip()
    if summary:
        history.append({"role": "system", "content": f"会话摘要：{_clip(summary, SUMMARY_LIMIT)}"})

    turns = list(session.get("turns") or [])[-recent_turns:]
    for turn in turns:
        user_query = str(turn.get("user_query") or "").strip()
        final_answer = str(turn.get("final_answer") or "").strip()
        if user_query:
            history.append({"role": "user", "content": _clip(user_query, ANSWER_SNIPPET_LIMIT)})
        if final_answer:
            history.append({"role": "assistant", "content": _clip(final_answer, ANSWER_SNIPPET_LIMIT)})
    return history


def build_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    """Keep the session file readable by persisting only high-signal state."""
    charts = [
        {
            "ok": c.get("ok"),
            "title": c.get("title") or c.get("chart_type") or "图表",
            "chart_type": c.get("chart_type"),
            "image_path": c.get("image_path"),
            "error_message": c.get("error_message"),
        }
        for c in (state.get("visualization_result") or {}).get("charts") or []
    ]
    return {
        "intent": state.get("intent"),
        "sub_questions": state.get("sub_questions") or [],
        "suggested_agents": state.get("suggested_agents") or [],
        "agents_done": state.get("agents_done") or {},
        "execution_log": state.get("execution_log") or [],
        "warnings": state.get("warnings") or [],
        "off_topic": bool(state.get("off_topic")),
        "chart_count": len(charts),
        "charts": charts,
        "sql_run_count": len(state.get("sql_runs") or []),
    }


def _compact_turns(session: dict[str, Any], *, max_turns: int = 6) -> list[dict[str, Any]]:
    turns = list(session.get("turns") or [])[-max_turns:]
    compact: list[dict[str, Any]] = []
    for turn in turns:
        resolved_task = turn.get("resolved_task") or turn.get("standalone_query") or ""
        compact.append(
            {
                "turn_id": turn.get("turn_id"),
                "user_query": _clip(str(turn.get("user_query") or ""), 300),
                "resolved_task": _clip(str(resolved_task), 500),
                "conversation_resolution": turn.get("conversation_resolution") or {},
                "final_answer": _clip(str(turn.get("final_answer") or ""), 700),
                "state_summary": turn.get("state_summary") or {},
            }
        )
    return compact


def update_memory_summary(
    session: dict[str, Any],
    *,
    model=None,
    max_turns: int = 6,
    limit: int = SUMMARY_LIMIT,
) -> str:
    if not (session.get("turns") or []):
        return str(session.get("memory_summary") or "").strip()

    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.decision_agent.llm import get_structured_llm

    payload = {
        "previous_memory_summary": _clip(str(session.get("memory_summary") or ""), limit),
        "recent_turns": _compact_turns(session, max_turns=max_turns),
    }
    llm = model or get_structured_llm()
    structured_model = llm.with_structured_output(SessionMemorySummary)
    response = structured_model.invoke(
        [
            SystemMessage(content=_load_summary_prompt()),
            HumanMessage(
                content="【会话记忆输入】\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
                + "\n\n请输出更新后的会话摘要。"
            ),
        ]
    )
    if isinstance(response, SessionMemorySummary):
        out = response
    elif isinstance(response, dict):
        out = SessionMemorySummary.model_validate(response)
    else:
        out = SessionMemorySummary.model_validate(response)
    if not out.memory_summary:
        raise ValueError("会话记忆摘要器没有返回 memory_summary。")
    return _clip(out.memory_summary, limit)
