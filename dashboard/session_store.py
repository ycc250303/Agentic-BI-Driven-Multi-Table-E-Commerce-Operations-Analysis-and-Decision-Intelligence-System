from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import streamlit as st

from dashboard.models import AgentProgress, ChatMessage, Conversation, VizRound


def init_session_store() -> None:
    if "conversations" not in st.session_state:
        st.session_state.conversations = {}
    if "active_conversation_id" not in st.session_state:
        conv = create_conversation()
        st.session_state.active_conversation_id = conv.id


def list_conversations() -> list[Conversation]:
    return list(st.session_state.conversations.values())


def get_active_conversation() -> Conversation | None:
    conv_id = st.session_state.get("active_conversation_id")
    if not conv_id:
        return None
    return st.session_state.conversations.get(conv_id)


def create_conversation(title: str = "新对话") -> Conversation:
    conv = Conversation(id=str(uuid.uuid4()), title=title)
    st.session_state.conversations[conv.id] = conv
    return conv


def set_active_conversation(conv_id: str) -> None:
    if conv_id in st.session_state.conversations:
        st.session_state.active_conversation_id = conv_id


def delete_conversation(conv_id: str) -> None:
    st.session_state.conversations.pop(conv_id, None)
    if st.session_state.get("active_conversation_id") == conv_id:
        remaining = list(st.session_state.conversations.values())
        if remaining:
            st.session_state.active_conversation_id = remaining[0].id
        else:
            st.session_state.active_conversation_id = create_conversation().id


def append_message(conv_id: str, message: ChatMessage) -> None:
    conv = st.session_state.conversations.get(conv_id)
    if conv is None:
        return
    conv.messages.append(message)
    if message.role == "user" and conv.title == "新对话":
        conv.title = message.content[:20] + ("…" if len(message.content) > 20 else "")


def set_last_state(conv_id: str, state: dict[str, Any]) -> None:
    conv = st.session_state.conversations.get(conv_id)
    if conv is not None:
        conv.last_state = state


def set_agent_progress(conv_id: str, progress: AgentProgress | None) -> None:
    conv = st.session_state.conversations.get(conv_id)
    if conv is not None:
        conv.agent_progress = progress


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


def new_user_message(content: str) -> ChatMessage:
    return ChatMessage(role="user", content=content, timestamp=datetime.now())


def new_assistant_message(
    content: str,
    *,
    decision_summary: str | None = None,
    warnings: list[str] | None = None,
    agent_progress: AgentProgress | None = None,
    viz_round: VizRound | None = None,
) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=content,
        timestamp=datetime.now(),
        decision_summary=decision_summary,
        warnings=warnings or [],
        agent_progress=agent_progress,
        viz_round=viz_round,
    )
