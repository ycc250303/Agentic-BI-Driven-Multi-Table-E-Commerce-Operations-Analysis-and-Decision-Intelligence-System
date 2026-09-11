from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from agents.sql_agent import pipeline as pipeline_mod
from agents.sql_agent import run as run_mod
from agents.sql_agent.pipeline import build_sql_pipeline, run_sql_pipeline_with_feedback

_PIPELINE_KEYS = {
    "user_query",
    "rewrite_json",
    "rewrite_attempts",
    "generate_sql_json",
    "check_sql_json",
    "execute_sql_json",
    "generate_sql_attempts",
}


class _FakeTool:
    def __init__(self, handler: Callable[[dict[str, Any], int], str]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._handler = handler

    def invoke(self, payload: dict[str, Any]) -> str:
        self.calls.append(payload)
        return self._handler(payload, len(self.calls))


def _const(value: str) -> Callable[[dict[str, Any], int], str]:
    return lambda _payload, _n: value


def _success_tools() -> tuple[_FakeTool, _FakeTool, _FakeTool, _FakeTool]:
    rewrite = _FakeTool(_const('{"query_for_sql":"q1"}'))
    generate = _FakeTool(_const('{"query_sqls":["SELECT 1"]}'))
    check = _FakeTool(_const('{"syntax_ok": true, "brief": "ok"}'))
    execute = _FakeTool(_const('{"ok": true, "error_message": null}'))
    return rewrite, generate, check, execute


def test_run_reexports_pipeline_entrypoints():
    assert run_mod.run_sql_pipeline_with_feedback is pipeline_mod.run_sql_pipeline_with_feedback
    assert run_mod.build_sql_pipeline is pipeline_mod.build_sql_pipeline


def test_check_failure_does_not_call_execute():
    rewrite, generate, check, execute = _success_tools()
    check = _FakeTool(_const('{"syntax_ok": false, "brief": "bad"}'))
    with patch.object(
        pipeline_mod, "_pipeline_tools", return_value=(rewrite, generate, check, execute)
    ):
        out = run_sql_pipeline_with_feedback("2017年哪个州的销售额最高？")

    assert execute.calls == []
    assert len(generate.calls) == 3
    assert len(check.calls) == 3
    skipped = json.loads(out["execute_sql_json"])
    assert skipped["error_stage"] == "skipped"
    assert out["generate_sql_attempts"] == 3


def test_check_pass_calls_execute_once():
    rewrite, generate, check, execute = _success_tools()
    with patch.object(
        pipeline_mod, "_pipeline_tools", return_value=(rewrite, generate, check, execute)
    ):
        out = run_sql_pipeline_with_feedback("hello")

    assert len(execute.calls) == 1
    assert json.loads(out["check_sql_json"])["syntax_ok"] is True
    assert json.loads(out["execute_sql_json"])["ok"] is True
    assert out["generate_sql_attempts"] == 1


def test_check_fail_then_pass_retries_then_executes():
    rewrite = _FakeTool(_const('{"query_for_sql":"q1"}'))
    generate = _FakeTool(_const('{"query_sqls":["SELECT 1"]}'))

    def check_handler(_payload: dict[str, Any], n: int) -> str:
        if n == 1:
            return '{"syntax_ok": false, "brief": "bad"}'
        return '{"syntax_ok": true, "brief": "ok"}'

    check = _FakeTool(check_handler)
    execute = _FakeTool(_const('{"ok": true, "error_message": null}'))
    with patch.object(
        pipeline_mod, "_pipeline_tools", return_value=(rewrite, generate, check, execute)
    ):
        out = run_sql_pipeline_with_feedback("hello")

    assert len(generate.calls) == 2
    assert len(execute.calls) == 1
    assert "check_sql 未通过" in generate.calls[1]["correction_context"]
    assert out["generate_sql_attempts"] == 2


def test_build_pipeline_matches_feedback_fields():
    tools_a = _success_tools()
    tools_b = _success_tools()
    with patch.object(pipeline_mod, "_pipeline_tools", return_value=tools_a):
        via_runnable = build_sql_pipeline().invoke("hello")
    with patch.object(pipeline_mod, "_pipeline_tools", return_value=tools_b):
        via_fn = run_sql_pipeline_with_feedback("hello")

    assert set(via_runnable) == _PIPELINE_KEYS
    assert set(via_fn) == _PIPELINE_KEYS
    assert via_runnable["user_query"] == via_fn["user_query"] == "hello"
