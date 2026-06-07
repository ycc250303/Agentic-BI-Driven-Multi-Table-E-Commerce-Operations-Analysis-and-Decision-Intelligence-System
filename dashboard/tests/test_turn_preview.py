from __future__ import annotations

from dashboard.models import ChatMessage, Conversation
from dashboard.session_store import turn_preview_already_in_conversation


def test_turn_preview_detects_when_answer_already_saved():
    conv = Conversation(
        id="s1",
        title="demo",
        messages=[
            ChatMessage(role="user", content="q"),
            ChatMessage(role="assistant", content="正式回答内容"),
        ],
        turn_count=1,
        updated_at="",
    )
    preview = {"final_answer": "正式回答内容"}
    assert turn_preview_already_in_conversation(conv, preview) is True


def test_turn_preview_needed_when_disk_not_synced_yet():
    conv = Conversation(
        id="s1",
        title="demo",
        messages=[ChatMessage(role="user", content="q")],
        turn_count=0,
        updated_at="",
    )
    preview = {"final_answer": "刚生成的回答"}
    assert turn_preview_already_in_conversation(conv, preview) is False
