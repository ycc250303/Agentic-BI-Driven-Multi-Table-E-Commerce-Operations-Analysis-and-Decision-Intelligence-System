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


def _render_assistant_turn(
    *,
    content: str,
    resolved_task: str | None = None,
    trace_events: list[dict[str, Any]] | None = None,
    decision_summary: str | None = None,
    warnings: list[str] | None = None,
) -> None:
    with st.chat_message("assistant"):
        if resolved_task:
            st.caption(f"本轮任务：{resolved_task}")
        if trace_events:
            render_trace_timeline(trace_events, live=False)
        st.markdown(content)
        if decision_summary:
            with st.expander("行动建议"):
                st.markdown(decision_summary)
        if warnings:
            for warning in warnings:
                st.warning(warning)


def _render_messages(conversation: Conversation) -> None:
    for msg in conversation.messages:
        if msg.role == "assistant":
            _render_assistant_turn(
                content=msg.content,
                resolved_task=msg.resolved_task,
                trace_events=msg.trace_events,
                decision_summary=msg.decision_summary,
                warnings=msg.warnings,
            )
        else:
            with st.chat_message(msg.role):
                st.markdown(msg.content)

    preview = session_store.get_turn_preview(conversation.id)
    if preview and not session_store.turn_preview_already_in_conversation(
        conversation, preview
    ):
        _render_assistant_turn(
            content=str(preview.get("final_answer") or ""),
            resolved_task=str(preview.get("resolved_task") or "") or None,
            trace_events=list(preview.get("trace_events") or []),
        )


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
    resolved_task = query
    error_message: str | None = None

    def on_event(event: dict[str, Any]) -> None:
        nonlocal user_query, resolved_task, error_message
        event_type = str(event.get("type") or "")

        if event_type == "turn.started":
            data = event.get("data") or {}
            user_query = str(data.get("user_query") or query)
            resolved_task = str(data.get("resolved_task") or user_query)
        elif event_type == "trace.event":
            trace = dict((event.get("data") or {}).get("trace") or {})
            if trace:
                traces.append(trace)
                with progress_slot.container():
                    render_trace_timeline(traces, live=True)
        elif event_type == "answer.final":
            data = event.get("data") or {}
            final_answer = str(data.get("final_answer") or "").strip()
            session_store.sync_live_viz_from_charts(
                conversation.id,
                user_query,
                list(data.get("charts") or []),
            )
            if final_answer:
                session_store.set_turn_preview(
                    conversation.id,
                    user_query=user_query,
                    final_answer=final_answer,
                    resolved_task=resolved_task,
                    trace_events=traces,
                )
            with progress_slot.container():
                render_trace_timeline(traces, live=False)
                if final_answer:
                    st.divider()
                    _render_assistant_turn(
                        content=final_answer,
                        resolved_task=resolved_task or None,
                    )
                else:
                    st.warning("分析已结束，但正式回答为空；请稍后刷新或重试。")
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
        refreshed = session_store.get_active_conversation()
        if refreshed and session_store.get_turn_preview(conversation.id):
            if session_store.turn_preview_already_in_conversation(
                refreshed,
                session_store.get_turn_preview(conversation.id) or {},
            ):
                session_store.clear_turn_preview(conversation.id)
        st.rerun()
        return

    prompt = st.chat_input("输入业务问题…")
    if not prompt:
        return

    session_store.set_pending_query(conversation.id, prompt)
    st.rerun()
