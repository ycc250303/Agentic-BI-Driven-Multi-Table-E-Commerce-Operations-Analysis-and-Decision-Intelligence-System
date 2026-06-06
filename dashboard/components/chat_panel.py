from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import streamlit as st

from dashboard.components.agent_progress import render_trace_timeline
from dashboard import session_store
from dashboard.models import Conversation
from dashboard.turn_runner import stream_turn

if TYPE_CHECKING:
    from streamlit.delta_generator import DeltaGenerator


def _render_messages(conversation: Conversation) -> None:
    for msg in conversation.messages:
        with st.chat_message(msg.role):
            if msg.role == "assistant" and msg.resolved_task:
                st.caption(f"本轮任务：{msg.resolved_task}")
            if msg.role == "assistant" and msg.trace_events:
                render_trace_timeline(msg.trace_events, live=False)
            st.markdown(msg.content)
            if msg.decision_summary:
                with st.expander("行动建议"):
                    st.markdown(msg.decision_summary)
            if msg.warnings:
                for warning in msg.warnings:
                    st.warning(warning)


def _run_turn(
    conversation: Conversation,
    query: str,
    *,
    progress_slot: DeltaGenerator,
    viz_placeholder: DeltaGenerator | None,
    render_viz: Callable[[], None] | None,
) -> None:
    traces: list[dict[str, Any]] = []
    session_store.set_live_viz(conversation.id, None)
    user_query = query
    error_message: str | None = None

    def on_event(event: dict[str, Any]) -> None:
        nonlocal user_query, error_message
        event_type = str(event.get("type") or "")

        if event_type == "turn.started":
            data = event.get("data") or {}
            user_query = str(data.get("user_query") or query)
        elif event_type == "trace.event":
            trace = dict((event.get("data") or {}).get("trace") or {})
            if trace:
                traces.append(trace)
                with progress_slot.container():
                    render_trace_timeline(traces, live=True)
        elif event_type == "answer.final":
            data = event.get("data") or {}
            session_store.sync_live_viz_from_charts(
                conversation.id,
                user_query,
                list(data.get("charts") or []),
            )
            if viz_placeholder is not None and render_viz is not None:
                with viz_placeholder.container():
                    render_viz()
        elif event_type == "turn.error":
            data = event.get("data") or {}
            error_message = f"{data.get('error_type', 'Error')}: {data.get('message', '未知错误')}"

    try:
        stream_turn(
            conversation.id,
            query,
            new_session=False,
            on_event=on_event,
        )
    except Exception as exc:
        error_message = str(exc)

    if error_message:
        session_store.set_live_viz(conversation.id, None)
        with progress_slot.container():
            st.error(error_message)


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

    pending_query = session_store.get_pending_query(conversation.id)

    with chat_scroll:
        _render_messages(conversation)
        if pending_query:
            with st.chat_message("user"):
                st.markdown(pending_query)
        progress_slot = st.empty()

    if pending_query:
        _run_turn(
            conversation,
            pending_query,
            progress_slot=progress_slot,
            viz_placeholder=viz_placeholder,
            render_viz=render_viz,
        )
        session_store.clear_pending_query(conversation.id)
        session_store.set_live_viz(conversation.id, None)
        st.rerun()
        return

    prompt = st.chat_input("输入业务问题…")
    if not prompt:
        return

    session_store.set_pending_query(conversation.id, prompt)
    st.rerun()
