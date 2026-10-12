from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import streamlit as st

from dashboard.models import Conversation, VizRound
from dashboard.session_projection import viz_round_from_turn

_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\s]+')
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _ok_charts(charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        c
        for c in charts
        if c.get("ok") and c.get("image_path") and Path(str(c["image_path"])).is_file()
    ]


def chart_download_filename(title: str, image_path: str) -> str:
    """把图表标题收成可下载的本地文件名。"""
    path = Path(image_path)
    suffix = path.suffix.lower() if path.suffix else ".png"
    if suffix not in _IMAGE_MIME:
        suffix = ".png"
    raw = (title or "").strip() or path.stem or "chart"
    safe = _UNSAFE_FILENAME.sub("_", raw).strip("._") or path.stem or "chart"
    return f"{safe[:80]}{suffix}"


def should_show_live_viz(viz_round: VizRound) -> bool:
    """是否展示 live 预览（有实际图表且未跳过）。"""
    return not viz_round.skipped and bool(_ok_charts(viz_round.charts))


def collect_viz_rounds(conversation: Conversation | None) -> list[VizRound]:
    if conversation is None:
        return []
    return [
        msg.viz_round
        for msg in conversation.messages
        if msg.role == "assistant" and msg.viz_round is not None
    ]


def render_viz_round(viz_round: VizRound, *, live: bool = False) -> None:
    """Dashboard 只展示已有 PNG（st.image），不重新规划或渲染。点击放大由页面灯箱处理。"""
    show_generating = live and should_show_live_viz(viz_round)
    prefix = "（生成中）" if show_generating else ""
    st.markdown(f"**{prefix}问：{viz_round.user_query}**")
    ok_charts = _ok_charts(viz_round.charts)

    if not ok_charts:
        if viz_round.skipped:
            st.info(viz_round.summary_text or "本轮未生成图表")
        else:
            st.info("本轮暂无图表")
        st.divider()
        return

    if viz_round.summary_text:
        st.caption(viz_round.summary_text)
    for chart in ok_charts:
        title = str(chart.get("title") or chart.get("chart_type") or "图表")
        st.image(str(chart["image_path"]), caption=title, width="stretch")
    st.divider()
