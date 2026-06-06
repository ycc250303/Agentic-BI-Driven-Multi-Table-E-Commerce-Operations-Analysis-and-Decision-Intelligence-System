from __future__ import annotations

import json

from agents.coordinator_agent.web_events import (
    encode_sse_event,
    result_to_sse,
    web_events_from_result,
)


def _sample_result() -> dict:
    return {
        "session_id": "s1",
        "turn_id": 2,
        "session_path": "runtime/sessions/s1.json",
        "user_query": "那 SP 州呢？",
        "resolved_task": "在上一轮分析基础上，聚焦 SP 州评估 casa_conforto 的表现。",
        "standalone_query": "分析 casa_conforto 在 SP 州的表现。",
        "final_answer": "SP 州表现较好。",
        "har_path": "runtime/har/s1_2.har",
        "har_entry_count": 3,
        "state_summary": {"intent": "descriptive"},
        "trace_events": [
            {
                "event_id": "turn-2-001",
                "agent": "coordinator_agent",
                "step": "decompose",
                "kind": "planning",
                "summary": "问题分解完成。",
            }
        ],
    }


def test_web_events_from_result_order_and_shape():
    events = web_events_from_result(_sample_result())

    assert [event["type"] for event in events] == [
        "turn.started",
        "trace.event",
        "answer.final",
        "har.saved",
        "turn.completed",
    ]
    assert events[0]["session_id"] == "s1"
    assert events[0]["data"]["resolved_task"].startswith("在上一轮")
    assert events[1]["data"]["trace"]["agent"] == "coordinator_agent"
    assert events[-1]["data"]["state_summary"]["intent"] == "descriptive"


def test_encode_sse_event_contains_event_id_and_json_data():
    event = web_events_from_result(_sample_result())[0]
    raw = encode_sse_event(event)

    assert raw.startswith("event: turn.started\n")
    assert "id: s1:2:started\n" in raw
    data_line = [line for line in raw.splitlines() if line.startswith("data: ")][0]
    data = json.loads(data_line.removeprefix("data: "))
    assert data["type"] == "turn.started"
    assert data["data"]["user_query"] == "那 SP 州呢？"


def test_result_to_sse_encodes_all_events():
    raw = result_to_sse(_sample_result())

    assert raw.count("event: ") == 5
    assert "event: answer.final" in raw
    assert "event: har.saved" in raw
