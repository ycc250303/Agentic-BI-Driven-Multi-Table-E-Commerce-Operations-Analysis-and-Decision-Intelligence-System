from __future__ import annotations

import json

import httpx

from agents.coordinator_agent.har_capture import (
    HttpxHarCapture,
    count_har_entries_by_agent,
    infer_agent_trace,
    summarize_har_entries,
    write_har,
)


def _chat_request(text: str) -> httpx.Request:
    payload = {
        "messages": [
            {"role": "system", "content": text},
            {"role": "user", "content": "请输出 JSON。"},
        ]
    }
    return httpx.Request(
        "POST",
        "https://api.example.test/v1/chat/completions",
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def test_infer_agent_trace_for_session_context_resolution():
    request = _chat_request("你是 Agentic BI 系统的会话语义解析器。")
    trace = infer_agent_trace(request.read(), request)

    assert trace["agent"] == "session_manager"
    assert trace["step"] == "resolve_conversation_context"


def test_infer_agent_trace_for_generate_sql():
    request = _chat_request("SQL 生成工具规则：请输出 query_sqls。")
    trace = infer_agent_trace(request.read(), request)

    assert trace["agent"] == "data_analysis_agent"
    assert trace["step"] == "generate_sql"


def test_write_har_empty_entries(tmp_path):
    path = write_har(tmp_path / "empty.har", [])
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["log"]["version"] == "1.2"
    assert data["log"]["entries"] == []


def test_summarize_har_entries_exposes_agent_ownership():
    entries = [
        {
            "startedDateTime": "2026-06-06T00:00:00.000Z",
            "time": 123.4,
            "request": {
                "method": "POST",
                "url": "https://api.example.test/v1/chat/completions",
            },
            "response": {"status": 200},
            "_agentic_bi": {
                "agent": "data_analysis_agent",
                "step": "generate_sql",
                "label": "data_analysis_agent.generate_sql",
                "source": "prompt_heuristic",
            },
        }
    ]

    summary = summarize_har_entries(entries)

    assert summary == [
        {
            "index": 1,
            "agent": "data_analysis_agent",
            "step": "generate_sql",
            "label": "data_analysis_agent.generate_sql",
            "source": "prompt_heuristic",
            "method": "POST",
            "url": "https://api.example.test/v1/chat/completions",
            "status": 200,
            "started_at": "2026-06-06T00:00:00.000Z",
            "time_ms": 123.4,
        }
    ]
    assert count_har_entries_by_agent(entries) == {"data_analysis_agent": 1}


def test_har_capture_context_restores_httpx_patch():
    original_sync = httpx.HTTPTransport.handle_request
    original_async = httpx.AsyncHTTPTransport.handle_async_request

    with HttpxHarCapture():
        assert httpx.HTTPTransport.handle_request is not original_sync
        assert httpx.AsyncHTTPTransport.handle_async_request is not original_async

    assert httpx.HTTPTransport.handle_request is original_sync
    assert httpx.AsyncHTTPTransport.handle_async_request is original_async
