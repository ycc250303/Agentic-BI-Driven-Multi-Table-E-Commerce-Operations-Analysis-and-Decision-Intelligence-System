from __future__ import annotations

import streamlit as st

from dashboard import session_store


def render_sidebar() -> None:
    st.title("Agentic BI")
    st.caption("Olist 电商运营分析与决策智能")

    if st.button("＋ 新建对话", use_container_width=True):
        conv = session_store.create_conversation()
        session_store.set_active_conversation(conv.id)
        st.rerun()

    st.divider()
    st.markdown("**会话记录**")

    active_id = st.session_state.get("active_conversation_id")
    for conv in reversed(session_store.list_conversations()):
        label = conv.title
        if conv.id == active_id:
            label = f"▸ {label}"
        if st.button(label, key=f"conv_{conv.id}", use_container_width=True):
            session_store.set_active_conversation(conv.id)
            st.rerun()

    st.divider()
    if active_id and st.button("删除当前会话", use_container_width=True):
        session_store.delete_conversation(active_id)
        st.rerun()
