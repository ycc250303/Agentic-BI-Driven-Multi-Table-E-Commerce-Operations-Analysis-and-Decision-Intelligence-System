from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


RECENT_TURN_LIMIT = 4
TEXT_LIMIT = 1600


class ConversationResolution(BaseModel):
    relation_to_previous: str = Field(default="new_topic")
    resolved_task: str = Field(default="")
    context_used: str = Field(default="")
    carried_over_goal: str = Field(default="")
    carried_over_subject: str = Field(default="")
    new_constraints: list[str] = Field(default_factory=list)
    changed_constraints: list[str] = Field(default_factory=list)
    needs_clarification: bool = Field(default=False)
    clarification_question: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator(
        "relation_to_previous",
        "resolved_task",
        "context_used",
        "carried_over_goal",
        "carried_over_subject",
        "clarification_question",
    )
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("new_constraints", "changed_constraints", mode="before")
    @classmethod
    def _normalize_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return [str(value).strip()] if str(value).strip() else []
        return [str(item).strip() for item in value if str(item or "").strip()]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_prompt() -> str:
    return (_project_root() / "config" / "coordinator_agent" / "resolve_conversation_context.md").read_text(
        encoding="utf-8"
    )


def _clip(text: str, limit: int = TEXT_LIMIT) -> str:
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "...(truncated)"


def _recent_turns(session: dict[str, Any], *, limit: int = RECENT_TURN_LIMIT) -> list[dict[str, Any]]:
    turns = list(session.get("turns") or [])[-limit:]
    compact: list[dict[str, Any]] = []
    for turn in turns:
        resolution = turn.get("conversation_resolution") or {}
        resolved_task = (
            turn.get("resolved_task")
            or turn.get("standalone_query")
            or resolution.get("resolved_task")
            or ""
        )
        compact.append(
            {
                "turn_id": turn.get("turn_id"),
                "user_query": _clip(str(turn.get("user_query") or ""), 400),
                "resolved_task": _clip(str(resolved_task or ""), 600),
                "conversation_resolution": {
                    "relation_to_previous": resolution.get("relation_to_previous"),
                    "context_used": _clip(str(resolution.get("context_used") or ""), 400),
                    "carried_over_goal": resolution.get("carried_over_goal"),
                    "carried_over_subject": resolution.get("carried_over_subject"),
                    "new_constraints": resolution.get("new_constraints") or [],
                    "changed_constraints": resolution.get("changed_constraints") or [],
                },
                "final_answer_summary": _clip(str(turn.get("final_answer") or ""), 800),
                "state_summary": turn.get("state_summary") or {},
            }
        )
    return compact


def _first_turn_resolution(user_query: str) -> ConversationResolution:
    # With no prior turns, there is no conversation reference to resolve.
    return ConversationResolution(
        relation_to_previous="new_topic",
        resolved_task=user_query,
        confidence=1.0,
    )


def _validate_resolution(output: ConversationResolution, *, user_query: str) -> ConversationResolution:
    if output.needs_clarification:
        if not output.clarification_question:
            raise ValueError("语义解析要求澄清，但没有给出澄清问题。")
        return output
    if not output.resolved_task:
        raise ValueError("语义解析没有给出本轮真实任务。")
    if not user_query.strip():
        raise ValueError("user_query 不能为空。")
    return output


def resolve_conversation_context(
    user_query: str,
    session: dict[str, Any],
    *,
    model=None,
) -> dict[str, Any]:
    """Resolve the current user utterance into a semantic BI task.

    The resolver is intentionally not rule-based. If previous context exists,
    the LLM must explicitly decide whether this turn continues, narrows,
    corrects, contrasts with, or replaces the prior task. Errors are allowed to
    surface instead of being hidden behind a guessed query.
    """
    query = str(user_query or "").strip()
    if not query:
        raise ValueError("user_query 不能为空。")

    if not (session.get("turns") or []):
        return _first_turn_resolution(query).model_dump()

    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.decision_agent.llm import get_llm

    payload = {
        "memory_summary": _clip(str(session.get("memory_summary") or "")),
        "recent_turns": _recent_turns(session),
        "current_user_query": query,
    }
    llm = model or get_llm()
    structured_model = llm.with_structured_output(ConversationResolution)
    response = structured_model.invoke(
        [
            SystemMessage(content=_load_prompt()),
            HumanMessage(
                content="【会话语义解析输入】\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
                + "\n\n请只输出结构化解析结果。"
            ),
        ]
    )
    if isinstance(response, ConversationResolution):
        resolution = response
    elif isinstance(response, dict):
        resolution = ConversationResolution.model_validate(response)
    else:
        resolution = ConversationResolution.model_validate(response)
    return _validate_resolution(resolution, user_query=query).model_dump()
