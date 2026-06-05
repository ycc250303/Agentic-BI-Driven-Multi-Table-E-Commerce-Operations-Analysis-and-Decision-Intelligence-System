from __future__ import annotations

import streamlit as st

from dashboard.models import Conversation
from dashboard import session_store
from dashboard.viz_helpers import collect_viz_rounds, render_viz_round


def render_viz_panel(conversation: Conversation | None) -> None:
    rounds = collect_viz_rounds(conversation)
    live = session_store.get_live_viz(conversation.id) if conversation else None

    if not rounds and live is None:
        st.info("提交问题后，图表将在此按提问分组展示")
        return

    if live is not None:
        render_viz_round(live, live=True)

    for viz_round in reversed(rounds):
        if live is not None and viz_round.user_query == live.user_query:
            continue
        render_viz_round(viz_round)
