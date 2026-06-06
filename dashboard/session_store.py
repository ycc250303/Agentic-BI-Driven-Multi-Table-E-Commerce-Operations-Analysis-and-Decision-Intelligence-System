from __future__ import annotations

from typing import Any

import streamlit as st

from agents.coordinator_agent.session_manager import SessionManager

from dashboard.models import Conversation, VizRound
from dashboard.session_projection import (
    list_item_to_conversation,
    session_to_conversation,
    viz_round_from_charts,
)
from dashboard.viz_helpers import should_show_live_viz


def get_manager() -> SessionManager:
    if "coordinator_session_manager" not in st.session_state:
        st.session_state.coordinator_session_manager = SessionManager()
    return st.session_state.coordinator_session_manager


def init_session_store() -> None:
    if "active_conversation_id" not in st.session_state:
        sessions = get_manager().list_sessions()
        st.session_state.active_conversation_id = (
            sessions[0]["session_id"] if sessions else None
        )


def list_conversations() -> list[Conversation]:
    return [
        list_item_to_conversation(item)
        for item in get_manager().list_sessions()
    ]


def get_active_conversation() -> Conversation | None:
    conv_id = st.session_state.get("active_conversation_id")
    if not conv_id:
        return None
    try:
        session = get_manager().load_session(str(conv_id))
    except FileNotFoundError:
        return None
    return session_to_conversation(session)


def create_conversation(title: str = "新对话") -> Conversation:
    session = get_manager().create_session(title=title)
    return session_to_conversation(session)


def set_active_conversation(conv_id: str) -> None:
    try:
        get_manager().load_session(conv_id)
    except FileNotFoundError:
        return
    st.session_state.active_conversation_id = conv_id


def delete_conversation(conv_id: str) -> None:
    manager = get_manager()
    manager.delete_session(conv_id)
    if st.session_state.get("active_conversation_id") == conv_id:
        remaining = manager.list_sessions()
        st.session_state.active_conversation_id = (
            remaining[0]["session_id"] if remaining else None
        )


def _pending_query_key(conv_id: str) -> str:
    return f"dashboard_pending_query_{conv_id}"


def set_pending_query(conv_id: str, query: str) -> None:
    st.session_state[_pending_query_key(conv_id)] = query


def get_pending_query(conv_id: str) -> str | None:
    value = st.session_state.get(_pending_query_key(conv_id))
    return str(value) if value else None


def clear_pending_query(conv_id: str) -> None:
    st.session_state.pop(_pending_query_key(conv_id), None)


def _live_viz_key(conv_id: str) -> str:
    return f"dashboard_live_viz_{conv_id}"


def set_live_viz(conv_id: str, viz_round: VizRound | None) -> None:
    key = _live_viz_key(conv_id)
    if viz_round is None:
        st.session_state.pop(key, None)
    else:
        st.session_state[key] = viz_round


def get_live_viz(conv_id: str) -> VizRound | None:
    return st.session_state.get(_live_viz_key(conv_id))


def sync_live_viz_from_charts(
    conv_id: str,
    user_query: str,
    charts: list[dict[str, Any]],
) -> bool:
    viz_round = viz_round_from_charts(user_query, charts)
    if viz_round is not None and should_show_live_viz(viz_round):
        set_live_viz(conv_id, viz_round)
        return True
    set_live_viz(conv_id, None)
    return False
