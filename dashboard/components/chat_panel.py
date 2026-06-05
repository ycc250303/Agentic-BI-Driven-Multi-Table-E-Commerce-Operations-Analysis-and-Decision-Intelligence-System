from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import streamlit as st

from dashboard.components.agent_progress import render_agent_progress
from dashboard.coordinator_runner import run_with_agent_progress
from dashboard import session_store
from dashboard.models import AgentProgress, Conversation
from dashboard.viz_helpers import viz_round_from_state

if TYPE_CHECKING:
    from streamlit.delta_generator import DeltaGenerator


def _format_decision_summary(state: dict[str, Any]) -> str | None:
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


def _render_messages(conversation: Conversation) -> None:
    for msg in conversation.messages:
        with st.chat_message(msg.role):
            if msg.role == "assistant" and msg.agent_progress is not None:
                render_agent_progress(msg.agent_progress)
            st.markdown(msg.content)
            if msg.decision_summary:
                with st.expander("行动建议"):
                    st.markdown(msg.decision_summary)
            if msg.warnings:
                for warning in msg.warnings:
                    st.warning(warning)


def _run_coordinator(
    conversation: Conversation,
    query: str,
    *,
    progress_slot: DeltaGenerator,
    viz_placeholder: DeltaGenerator | None,
    render_viz: Callable[[], None] | None,
) -> AgentProgress | None:
    final_progress: AgentProgress | None = None

    def on_progress(progress: AgentProgress, state: dict[str, Any]) -> None:
        nonlocal final_progress
        final_progress = progress
        with progress_slot.container():
            render_agent_progress(progress)
        if state.get("visualization_result"):
            session_store.set_last_state(conversation.id, state)
            live = viz_round_from_state(query, state)
            if live is not None:
                session_store.set_live_viz(conversation.id, live)
            if viz_placeholder is not None and render_viz is not None:
                with viz_placeholder.container():
                    render_viz()

    try:
        final_state = run_with_agent_progress(query, on_progress=on_progress)
    except Exception as exc:
        session_store.set_live_viz(conversation.id, None)
        conv = session_store.get_active_conversation()
        err_viz = viz_round_from_state(query, (conv.last_state if conv else None) or {})
        session_store.append_message(
            conversation.id,
            session_store.new_assistant_message(
                f"分析失败：{exc}",
                warnings=[str(exc)],
                agent_progress=final_progress,
                viz_round=err_viz,
            ),
        )
        return final_progress

    session_store.set_last_state(conversation.id, final_state)
    session_store.set_live_viz(conversation.id, None)
    answer = str(final_state.get("final_answer") or "（无回答）")
    warnings = list(final_state.get("warnings") or [])
    decision_summary = _format_decision_summary(final_state)
    viz_round = viz_round_from_state(query, final_state)
    session_store.append_message(
        conversation.id,
        session_store.new_assistant_message(
            answer,
            decision_summary=decision_summary,
            warnings=warnings,
            agent_progress=final_progress,
            viz_round=viz_round,
        ),
    )
    return final_progress


def handle_chat_panel(
    conversation: Conversation | None,
    *,
    chat_scroll: DeltaGenerator,
    viz_placeholder: DeltaGenerator | None = None,
    render_viz: Callable[[], None] | None = None,
) -> None:
    if conversation is None:
        with chat_scroll:
            st.warning("请先新建或选择一个会话")
        return

    with chat_scroll:
        _render_messages(conversation)
        progress_slot = st.empty()

    pending_query = session_store.get_pending_query(conversation.id)
    if pending_query:
        _run_coordinator(
            conversation,
            pending_query,
            progress_slot=progress_slot,
            viz_placeholder=viz_placeholder,
            render_viz=render_viz,
        )
        session_store.clear_pending_query(conversation.id)
        st.rerun()
        return

    prompt = st.chat_input("输入业务问题…")
    if not prompt:
        return

    session_store.append_message(
        conversation.id,
        session_store.new_user_message(prompt),
    )
    session_store.set_pending_query(conversation.id, prompt)
    st.rerun()
