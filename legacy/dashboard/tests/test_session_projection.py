from __future__ import annotations

from dashboard.session_projection import (
    format_decision_summary,
    session_to_conversation,
    turns_to_messages,
    viz_round_from_charts,
    viz_round_from_turn,
)
from dashboard.viz_helpers import should_show_live_viz


def test_turns_to_messages_user_and_assistant():
    turns = [
        {
            "turn_id": 1,
            "created_at": "2026-06-06T12:00:00+08:00",
            "user_query": "2017 GMV？",
            "resolved_task": "2017 GMV？",
            "final_answer": "SP 州最高。",
            "trace_events": [{"agent": "coordinator_agent", "step": "decompose"}],
            "state_summary": {"warnings": []},
        }
    ]
    messages = turns_to_messages(turns)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert messages[1].content == "SP 州最高。"
    assert len(messages[1].trace_events) == 1


def test_turns_to_messages_shows_resolved_task():
    turns = [
        {
            "user_query": "那 SP 州呢？",
            "resolved_task": "在上一轮框架下分析 SP 州 GMV。",
            "final_answer": "SP 州 GMV 为 …",
            "state_summary": {},
        }
    ]
    messages = turns_to_messages(turns)
    assert messages[1].resolved_task == "在上一轮框架下分析 SP 州 GMV。"


def test_viz_round_from_turn_skipped():
    turn = {
        "user_query": "重量与运费关系？",
        "state": {
            "visualization_result": {
                "skipped": True,
                "summary_text": "问题未体现可视化需求，跳过出图。",
                "charts": [],
            }
        },
        "state_summary": {"charts": [], "chart_count": 0},
    }
    viz = viz_round_from_turn(turn)
    assert viz is not None
    assert viz.skipped is True
    assert not should_show_live_viz(viz)


def test_viz_round_from_charts_live_preview():
    viz = viz_round_from_charts(
        "q",
        [{"ok": True, "image_path": __file__, "title": "chart"}],
    )
    assert viz is not None
    assert should_show_live_viz(viz)


def test_format_decision_summary():
    state = {
        "decision_result": {
            "action_plan": [{"action": "优化物流", "priority": "高"}],
        }
    }
    text = format_decision_summary(state)
    assert text is not None
    assert "优化物流" in text


def test_session_to_conversation():
    session = {
        "session_id": "s1",
        "title": "demo",
        "updated_at": "2026-06-06T12:00:00+08:00",
        "turns": [{"user_query": "q", "final_answer": "a", "state_summary": {}}],
    }
    conv = session_to_conversation(session)
    assert conv.id == "s1"
    assert conv.turn_count == 1
    assert len(conv.messages) == 2
