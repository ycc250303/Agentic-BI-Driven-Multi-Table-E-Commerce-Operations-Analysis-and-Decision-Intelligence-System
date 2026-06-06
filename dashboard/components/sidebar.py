from __future__ import annotations

import streamlit as st

from dashboard import session_store
from dashboard.constants import SIDEBAR_CONV_COL_WEIGHTS
from dashboard.models import Conversation
from dashboard.text_utils import format_session_button_label


def _render_conversation_row(conv: Conversation, *, active_id: str | None) -> None:
    is_active = conv.id == active_id
    label = format_session_button_label(conv.title, active=is_active)
    title_weight, delete_weight = SIDEBAR_CONV_COL_WEIGHTS

    col_title, col_delete = st.columns([title_weight, delete_weight], gap="small")
    with col_title:
        if st.button(
            label,
            key=f"conv_{conv.id}",
            type="tertiary",
            use_container_width=True,
            help=conv.title,
        ):
            session_store.set_active_conversation(conv.id)
            st.rerun()
    with col_delete:
        if st.button(
            "🗑",
            key=f"del_{conv.id}",
            type="tertiary",
            help="删除会话",
        ):
            session_store.delete_conversation(conv.id)
            st.rerun()


def render_sidebar() -> None:
    st.title("Agentic BI")
    st.caption("Olist 电商运营分析与决策智能系统")

    if st.button("＋ 新建对话", use_container_width=True):
        conv = session_store.create_conversation()
        session_store.set_active_conversation(conv.id)
        st.rerun()

    st.markdown("**会话记录**")

    active_id = st.session_state.get("active_conversation_id")
    for conv in reversed(session_store.list_conversations()):
        _render_conversation_row(conv, active_id=active_id)
