from __future__ import annotations

import streamlit as st

# 独立滚动面板高度（像素）；与 viewport 大致对齐，避免整页联动滚动
PANEL_SCROLL_HEIGHT = 700


def inject_independent_panel_styles() -> None:
    """限制主区域尺寸：左右面板各自纵向滚动，整体不超出 viewport 宽度。"""
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"],
        section.main {
            max-width: 100vw;
            overflow-x: hidden;
        }
        section.main > div.block-container {
            padding-top: 1rem;
            padding-bottom: 0.5rem;
            max-width: 100%;
            box-sizing: border-box;
        }
        div[data-testid="column"] {
            min-width: 0;
            overflow-x: hidden;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--secondary-background-color);
            border-radius: 0.5rem;
            max-width: 100%;
            box-sizing: border-box;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] > div {
            padding: 0.25rem 0.5rem;
        }
        section.main img {
            max-width: 100%;
            height: auto;
        }
        section.main [data-testid="stChatMessage"],
        section.main [data-testid="stMarkdownContainer"] {
            word-break: break-word;
            overflow-wrap: anywhere;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
