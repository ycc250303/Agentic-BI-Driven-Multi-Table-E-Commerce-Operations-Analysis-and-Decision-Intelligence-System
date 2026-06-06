from __future__ import annotations

from datetime import datetime
from typing import Any

from dashboard.models import ChatMessage, Conversation, VizRound


def format_decision_summary(state: dict[str, Any]) -> str | None:
    decision = state.get("decision_result") or {}
    plans = decision.get("action_plan") or []
    if not plans:
        return None
    lines = ["**行动建议（节选）**"]
    for item in plans[:3]:
        action = item.get("action") or ""
        priority = item.get("priority") or ""
        lines.append(f"- [{priority}] {action}")
    return "\n".join(lines)


def viz_round_from_turn(turn: dict[str, Any]) -> VizRound | None:
    user_query = str(turn.get("user_query") or "")
    summary = turn.get("state_summary") or {}
    charts = list(summary.get("charts") or [])
    state = turn.get("state") or {}
    viz = state.get("visualization_result") or {}
    if viz:
        skipped = bool(viz.get("skipped"))
        summary_text = viz.get("summary_text")
        if not charts:
            charts = list(viz.get("charts") or [])
    else:
        skipped = summary.get("chart_count", 0) == 0 and not charts
        summary_text = None

    if not charts and not skipped:
        return None
    return VizRound(
        user_query=user_query,
        charts=charts,
        summary_text=summary_text,
        skipped=skipped,
    )


def viz_round_from_charts(
    user_query: str,
    charts: list[dict[str, Any]],
    *,
    skipped: bool = False,
    summary_text: str | None = None,
) -> VizRound | None:
    if not charts and not skipped:
        return None
    return VizRound(
        user_query=user_query,
        charts=charts,
        summary_text=summary_text,
        skipped=skipped,
    )


def _parse_turn_time(turn: dict[str, Any]) -> datetime:
    raw = str(turn.get("created_at") or "").strip()
    if not raw:
        return datetime.now()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now()


def turns_to_messages(turns: list[dict[str, Any]]) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for turn in turns:
        user_query = str(turn.get("user_query") or "")
        if not user_query:
            continue
        ts = _parse_turn_time(turn)
        messages.append(
            ChatMessage(role="user", content=user_query, timestamp=ts),
        )
        resolved = str(
            turn.get("resolved_task") or turn.get("standalone_query") or ""
        ).strip()
        state = turn.get("state") or {}
        state_summary = turn.get("state_summary") or {}
        messages.append(
            ChatMessage(
                role="assistant",
                content=str(turn.get("final_answer") or ""),
                timestamp=ts,
                resolved_task=resolved if resolved and resolved != user_query else None,
                decision_summary=format_decision_summary(state),
                warnings=list(state_summary.get("warnings") or []),
                trace_events=list(turn.get("trace_events") or []),
                viz_round=viz_round_from_turn(turn),
            ),
        )
    return messages


def session_to_conversation(session: dict[str, Any]) -> Conversation:
    turns = list(session.get("turns") or [])
    sid = str(session.get("session_id") or "")
    return Conversation(
        id=sid,
        title=str(session.get("title") or sid or "新对话"),
        messages=turns_to_messages(turns),
        turn_count=len(turns),
        updated_at=str(session.get("updated_at") or ""),
    )


def list_item_to_conversation(item: dict[str, Any]) -> Conversation:
    return Conversation(
        id=str(item.get("session_id") or ""),
        title=str(item.get("title") or item.get("session_id") or "新对话"),
        messages=[],
        turn_count=int(item.get("turn_count") or 0),
        updated_at=str(item.get("updated_at") or ""),
    )
