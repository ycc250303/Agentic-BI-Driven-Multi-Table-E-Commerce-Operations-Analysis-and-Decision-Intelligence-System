from __future__ import annotations

import streamlit as st

from dashboard.agent_labels import label_for
from dashboard.models import AgentProgress


def render_agent_progress(progress: AgentProgress | None) -> None:
    if progress is None:
        return

    title = "分析完成" if progress.finished else "分析进行中"
    with st.status(title, expanded=True):
        for step_id in progress.completed:
            label = label_for(step_id) or step_id
            st.success(f"✓ {label} 已完成")

        if progress.current and not progress.finished:
            label = progress.current_label or progress.current
            st.info(f"⟳ {label} 正在执行")
