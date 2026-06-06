from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from agents.coordinator_agent.session_manager import CoordinatorRunOptions

from dashboard import session_store

DEFAULT_RUN_OPTIONS = CoordinatorRunOptions(
    use_llm_plan=True,
    use_llm_viz=True,
    use_llm_synthesize=True,
    full_state=True,
)


def stream_turn(
    session_id: str | None,
    query: str,
    *,
    new_session: bool = False,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run one coordinator turn via SessionManager; yield web_events-shaped dicts."""
    manager = session_store.get_manager()
    last_result: dict[str, Any] = {}

    for event in manager.stream_turn_events(
        query=query,
        session_id=session_id,
        new_session=new_session,
        options=DEFAULT_RUN_OPTIONS,
    ):
        if on_event is not None:
            on_event(event)
        event_type = str(event.get("type") or "")
        if event_type == "answer.final":
            last_result.update(event.get("data") or {})
            last_result["session_id"] = event.get("session_id")
            last_result["turn_id"] = event.get("turn_id")
        elif event_type == "turn.completed":
            data = event.get("data") or {}
            last_result["session_path"] = data.get("session_path")
            last_result["state_summary"] = data.get("state_summary")
            last_result["session_id"] = event.get("session_id")
            last_result["turn_id"] = event.get("turn_id")
        elif event_type == "turn.started":
            data = event.get("data") or {}
            last_result["user_query"] = data.get("user_query")
            last_result["resolved_task"] = data.get("resolved_task")
            last_result["session_id"] = event.get("session_id")
            last_result["turn_id"] = event.get("turn_id")

    if last_result.get("session_id"):
        st_session_id = str(last_result["session_id"])
        session_store.set_active_conversation(st_session_id)
        st.session_state.active_conversation_id = st_session_id

    return last_result
