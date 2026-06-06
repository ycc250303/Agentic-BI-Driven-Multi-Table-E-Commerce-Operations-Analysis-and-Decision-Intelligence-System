from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from dashboard.models import Conversation, VizRound


def _ok_charts(charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        c
        for c in charts
        if c.get("ok") and c.get("image_path") and Path(str(c["image_path"])).is_file()
    ]


def should_show_live_viz(viz_round: VizRound) -> bool:
    """是否展示 live 预览（有实际图表且未跳过）。"""
    return not viz_round.skipped and bool(_ok_charts(viz_round.charts))


def viz_round_from_state(user_query: str, state: dict[str, Any]) -> VizRound | None:
    viz = state.get("visualization_result") or {}
    charts = list(viz.get("charts") or [])
    if not charts and not viz.get("skipped"):
        return None
    return VizRound(
        user_query=user_query,
        charts=charts,
        summary_text=viz.get("summary_text"),
        skipped=bool(viz.get("skipped")),
    )


def collect_viz_rounds(conversation: Conversation | None) -> list[VizRound]:
    if conversation is None:
        return []
    return [
        msg.viz_round
        for msg in conversation.messages
        if msg.role == "assistant" and msg.viz_round is not None
    ]


def render_viz_round(viz_round: VizRound, *, live: bool = False) -> None:
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
        title = chart.get("title") or chart.get("chart_type") or "图表"
        st.image(str(chart["image_path"]), caption=str(title), use_container_width=True)
    st.divider()
