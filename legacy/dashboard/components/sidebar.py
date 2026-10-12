from __future__ import annotations

import streamlit as st

from agents.common.llm import (
    LLM_PROVIDER_LABELS,
    LLM_PROVIDERS,
    has_provider_api_key,
    provider_api_key_env,
)
from dashboard import session_store
from dashboard.constants import DEEPSEEK_THINKING_SESSION_KEY
from dashboard.constants import LLM_PROVIDER_SESSION_KEY
from dashboard.constants import SIDEBAR_CONV_COL_WEIGHTS
from dashboard.models import Conversation
from dashboard.text_utils import format_session_button_label


def _session_help_text(conv: Conversation) -> str:
    if conv.turn_count:
        return f"{conv.title}\n{conv.turn_count} 轮"
    return conv.title


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
            width="stretch",
            help=_session_help_text(conv),
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

    with st.expander("模型设置", expanded=False):
        st.selectbox(
            "模型",
            options=list(LLM_PROVIDERS),
            format_func=lambda p: LLM_PROVIDER_LABELS.get(p, p),
            key=LLM_PROVIDER_SESSION_KEY,
            help="DeepSeek 与通义千问共用同一套编排；Qwen 固定 qwen3.8-max。",
        )
        thinking = st.toggle(
            "思考模式",
            help="开启后自由文本步骤会先推理再作答，响应更慢。结构化查数 / 分解 / 路由仍关闭思考（API 限制）。",
            key=DEEPSEEK_THINKING_SESSION_KEY,
        )
        session_store.apply_llm_settings_from_session()
        provider = str(st.session_state.get(LLM_PROVIDER_SESSION_KEY) or "deepseek")
        if not has_provider_api_key(provider):
            st.warning(
                f"当前模型缺少 {provider_api_key_env(provider)}，请在项目根目录 .env 中配置。"
            )
        if thinking:
            st.caption(
                "当前：思考模式已开启（汇总等自由文本步骤）；"
                "分解 / 路由 / SQL 结构化步骤仍关闭思考（API 限制）"
            )
        else:
            st.caption("当前：思考模式已关闭（响应更快）")

    if st.button("＋ 新建对话", width="stretch"):
        conv = session_store.create_conversation()
        session_store.set_active_conversation(conv.id)
        st.rerun()

    st.markdown("**会话记录**")

    active_id = st.session_state.get("active_conversation_id")
    conversations = session_store.list_conversations()
    if not conversations:
        st.caption("暂无会话")
        return

    for conv in conversations:
        _render_conversation_row(conv, active_id=active_id)
