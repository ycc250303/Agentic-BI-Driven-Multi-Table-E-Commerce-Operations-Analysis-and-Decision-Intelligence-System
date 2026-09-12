from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from dashboard.constants import PANEL_SCROLL_HEIGHT

_STYLES_PATH = Path(__file__).with_name("styles.css")
_LIGHTBOX_JS_PATH = Path(__file__).with_name("chart_lightbox.js")


def inject_dashboard_styles() -> None:
    """注入 dashboard 全局样式（主区域布局 + 侧边栏会话列表 + 图表灯箱）。"""
    css = _STYLES_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    _inject_chart_lightbox()


def _inject_chart_lightbox() -> None:
    """经 components.html 注入脚本：不受 DOMPurify 剥离，可写回主页面 DOM。"""
    script = _LIGHTBOX_JS_PATH.read_text(encoding="utf-8")
    components.html(f"<script>{script}</script>", height=0, scrolling=False)
