"""SQL Agent 流水线编排：rewrite → generate → check → execute。

rewrite 最多 3 次；generate 最多 3 次（check 未通过或 execute 报错则写入
correction_context 重试）。不负责 CLI。

对外入口：`run_sql_pipeline_with_feedback`（dict + 可选逐步回调）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from agents.common.llm import get_structured_llm
from agents.sql_agent.tools.check_sql import build_check_sql_tool
from agents.sql_agent.tools.execute_sql import build_execute_sql_tool
from agents.sql_agent.tools.generate_sql import build_generate_sql_tool
from agents.sql_agent.tools.rewrite_to_query import build_rewrite_to_query_tool

MAX_REWRITE_ATTEMPTS = 3
MAX_GENERATE_ATTEMPTS = 3

_EXECUTE_SKIPPED_STUB = {
    "ok": False,
    "executed": False,
    "error_stage": "skipped",
    "error_message": (
        "未执行 execute_sql：在完成 3 次生成尝试前从未出现 check_sql 通过后的执行结果"
    ),
}

def _coerce_user_query(x: str | dict[str, Any]) -> str:
    if isinstance(x, dict):
        return str(x["user_query"])
    return str(x)


def _json_load_dict(raw_json: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw_json)
        if isinstance(data, dict):
            return data
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_check_syntax_ok(check_json: str) -> tuple[bool, str]:
    d = _json_load_dict(check_json)
    if d is None:
        return False, "check_sql 返回非合法 JSON"
    ok = d.get("syntax_ok") is True
    brief = str(d.get("brief") or "")
    return ok, brief


def _execute_error_message_nonempty(exec_json: str) -> tuple[bool, str]:
    d = _json_load_dict(exec_json)
    if d is None:
        return True, "execute_sql 返回非合法 JSON"
    msg = d.get("error_message")
    if msg is None:
        return False, ""
    s = str(msg).strip()
    return bool(s), s


def _pipeline_tools(model=None) -> tuple[Any, Any, Any, Any]:
    structured_llm = model or get_structured_llm()
    return (
        build_rewrite_to_query_tool(structured_llm),
        build_generate_sql_tool(structured_llm),
        build_check_sql_tool(),
        build_execute_sql_tool(),
    )


def _run_rewrite(
    user_query: str,
    *,
    rewrite_tool: Any,
    emit: Callable[[str, str], None] | None,
) -> tuple[str, int, list[str]]:
    rewrite_json = ""
    attempts_used = 0
    feedback_lines: list[str] = []

    for _ in range(MAX_REWRITE_ATTEMPTS):
        attempts_used += 1
        try:
            rewrite_json = rewrite_tool.invoke(
                {
                    "query": user_query,
                    "correction_context": "\n\n".join(feedback_lines),
                }
            )
        except Exception as e:
            feedback_lines.append(f"[rewrite_to_query 失败] {e}")
            continue
        if emit:
            emit("rewrite_to_query_tool", rewrite_json)
        return rewrite_json, attempts_used, []

    if not rewrite_json.strip():
        rewrite_json = json.dumps(
            {
                "query_for_sql": "",
                "sub_questions": [],
                "hit_pre_agg_view": False,
                "candidate_views": [],
                "confidence": 0.0,
            },
            ensure_ascii=False,
        )
    return rewrite_json, attempts_used, feedback_lines


def _run_retry_loop(
    rewrite_json: str,
    *,
    generate_tool: Any,
    check_tool: Any,
    execute_tool: Any,
    emit: Callable[[str, str], None] | None,
    initial_feedback: list[str] | None = None,
) -> tuple[str, str, str, int]:
    """返回 (generate_sql_json, check_sql_json, execute_sql_json, attempts_used)。"""
    feedback_lines: list[str] = list(initial_feedback or [])
    sql_json = ""
    check_json = ""
    exec_json = ""
    attempts_used = 0
    last_generate_error = ""

    for _ in range(MAX_GENERATE_ATTEMPTS):
        attempts_used += 1
        ctx = "\n\n".join(feedback_lines)
        try:
            sql_json = generate_tool.invoke(
                {"rewrite_json": rewrite_json, "correction_context": ctx}
            )
        except Exception as e:
            last_generate_error = str(e)
            feedback_lines.append(f"[generate_sql 失败] {last_generate_error}")
            continue
        if emit:
            emit("generate_sql_tool", sql_json)

        check_json = check_tool.invoke({"generate_sql_json": sql_json})
        if emit:
            emit("check_sql_tool", check_json)

        check_ok, brief = _parse_check_syntax_ok(check_json)
        if not check_ok:
            feedback_lines.append(f"[check_sql 未通过] {brief}")
            continue

        exec_json = execute_tool.invoke({"generate_sql_json": sql_json})
        if emit:
            emit("execute_sql_tool", exec_json)

        has_err, err_s = _execute_error_message_nonempty(exec_json)
        if not has_err:
            break

        feedback_lines.append(f"[execute_sql 失败] {err_s}")

    if not exec_json.strip():
        exec_json = json.dumps(_EXECUTE_SKIPPED_STUB, ensure_ascii=False)
        if emit:
            emit("execute_sql_tool", exec_json)
    if not check_json.strip():
        msg = (
            "未获得可校验的 generate_sql 输出。"
            + (f" 最近错误：{last_generate_error}" if last_generate_error else "")
        )
        check_json = json.dumps({"syntax_ok": False, "brief": msg}, ensure_ascii=False)

    return sql_json, check_json, exec_json, attempts_used


def _run_pipeline(
    user_query: str,
    *,
    rewrite_tool: Any,
    generate_tool: Any,
    check_tool: Any,
    execute_tool: Any,
    on_tool_end: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """跑完整条流水线并拼装对外 dict。"""

    def emit(tool_name: str, payload: str) -> None:
        if on_tool_end:
            on_tool_end(tool_name, payload)

    rewrite_json, rewrite_attempts, rewrite_feedback = _run_rewrite(
        user_query,
        rewrite_tool=rewrite_tool,
        emit=emit,
    )
    sql_json, check_json, exec_json, attempts_used = _run_retry_loop(
        rewrite_json,
        generate_tool=generate_tool,
        check_tool=check_tool,
        execute_tool=execute_tool,
        emit=emit,
        initial_feedback=rewrite_feedback,
    )
    return {
        "user_query": user_query,
        "rewrite_json": rewrite_json,
        "rewrite_attempts": rewrite_attempts,
        "generate_sql_json": sql_json,
        "check_sql_json": check_json,
        "execute_sql_json": exec_json,
        "generate_sql_attempts": attempts_used,
    }


def run_sql_pipeline_with_feedback(
    user_query: str | dict[str, Any],
    *,
    model=None,
    on_tool_end: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """
    跑完整条流水线；若提供 `on_tool_end(tool_name, json_str)`，则在每个工具返回后立即调用。
    """
    rewrite_tool, generate_tool, check_tool, execute_tool = _pipeline_tools(model)
    uq = _coerce_user_query(user_query)
    return _run_pipeline(
        uq,
        rewrite_tool=rewrite_tool,
        generate_tool=generate_tool,
        check_tool=check_tool,
        execute_tool=execute_tool,
        on_tool_end=on_tool_end,
    )
