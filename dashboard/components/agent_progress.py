from __future__ import annotations

import streamlit as st

from dashboard.agent_labels import label_for


def _render_trace_items(traces: list[dict]) -> None:
    for trace in traces:
        agent = label_for(str(trace.get("agent") or "")) or str(trace.get("agent") or "Agent")
        step = str(trace.get("step") or trace.get("kind") or "event")
        summary = str(trace.get("summary") or trace.get("title") or "").strip()
        st.markdown(f"**{agent}** · `{step}`")
        if summary:
            st.caption(summary)
        sqls = (trace.get("metadata") or {}).get("sqls") or []
        for sql in sqls[:2]:
            st.code(str(sql), language="sql")


def render_trace_timeline(traces: list[dict], *, live: bool = False) -> None:
    """渲染 Agent 编排过程。live=True 为运行中；完成后用 expander 展示全部步骤。"""
    if not traces:
        return

    if live:
        with st.status("分析进行中", expanded=True):
            _render_trace_items(traces)
        return

    label = f"Agent 过程（共 {len(traces)} 步）"
    with st.expander(label, expanded=False):
        _render_trace_items(traces)
