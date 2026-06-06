from __future__ import annotations

from pathlib import Path

import streamlit as st

from dashboard.constants import PANEL_SCROLL_HEIGHT

_STYLES_PATH = Path(__file__).with_name("styles.css")


def inject_dashboard_styles() -> None:
    """注入 dashboard 全局样式（主区域布局 + 侧边栏会话列表）。"""
    css = _STYLES_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
