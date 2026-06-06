from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components.chat_panel import handle_chat_panel
from dashboard.components.sidebar import render_sidebar
from dashboard.components.viz_panel import render_viz_panel
from dashboard.layout import PANEL_SCROLL_HEIGHT, inject_dashboard_styles
from dashboard import session_store


def main() -> None:
    st.set_page_config(
        page_title="Agentic BI",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    inject_dashboard_styles()
    session_store.init_session_store()
    conversation = session_store.get_active_conversation()

    with st.sidebar:
        render_sidebar()

    col_chat, col_viz = st.columns([3, 2], gap="medium")

    with col_viz:
        st.subheader("可视化")
        viz_scroll = st.container(height=PANEL_SCROLL_HEIGHT, border=True)
        with viz_scroll:
            viz_placeholder = st.empty()
            with viz_placeholder.container():
                render_viz_panel(conversation)

    with col_chat:
        st.subheader("对话")
        chat_scroll = st.container(height=PANEL_SCROLL_HEIGHT, border=True)
        handle_chat_panel(
            conversation,
            chat_scroll=chat_scroll,
            viz_placeholder=viz_placeholder,
            render_viz=lambda: render_viz_panel(session_store.get_active_conversation()),
        )


if __name__ == "__main__":
    main()
