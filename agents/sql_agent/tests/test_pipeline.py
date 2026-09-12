from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from agents.sql_agent import pipeline as pipeline_mod
from agents.sql_agent.pipeline import run_sql_pipeline_with_feedback

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

    assert set(out) == _PIPELINE_KEYS
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
    assert "格式与只读校验未通过" in generate.calls[1]["correction_context"]
    assert out["generate_sql_attempts"] == 2


def test_scalar_row_shape_mismatch_retries_generate():
    rewrite = _FakeTool(
        _const(
            json.dumps(
                {
                    "query_for_sql": "q",
                    "sub_questions": [
                        {
                            "id": "q1",
                            "question_zh": "全平台 GMV",
                            "metric_key": "total_gmv",
                            "dimensions": [],
                            "aggregation": "",
                            "scope": {"kind": "platform"},
                        }
                    ],
                    "hit_pre_agg_view": False,
                    "candidate_views": [],
                    "confidence": 0.9,
                }
            )
        )
    )
    generate = _FakeTool(
        _const(
            '{"query_sqls":["SELECT SUM(`total_gmv`) AS `total_gmv` FROM `mv_monthly_sales`"]}'
        )
    )
    check = _FakeTool(_const('{"syntax_ok": true, "brief": "ok"}'))

    def execute_handler(_payload: dict[str, Any], n: int) -> str:
        rows = 12 if n == 1 else 1
        return json.dumps(
            {
                "ok": True,
                "error_message": None,
                "results": [{"index": 0, "ok": True, "row_count_returned": rows}],
            }
        )

    execute = _FakeTool(execute_handler)
    with patch.object(
        pipeline_mod, "_pipeline_tools", return_value=(rewrite, generate, check, execute)
    ):
        out = run_sql_pipeline_with_feedback("hello")

    assert len(execute.calls) == 2
    assert len(generate.calls) == 2
    assert "标量行数与计划不一致" in generate.calls[1]["correction_context"]
    assert out["generate_sql_attempts"] == 2
    assert json.loads(out["execute_sql_json"])["results"][0]["row_count_returned"] == 1
