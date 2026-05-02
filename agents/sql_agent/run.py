"""
SQL Agent 入口：用 LangChain Runnable 将流程固定为
用户自然语言 → rewrite_to_query_tool → generate_sql_tool → check_sql_tool → execute_sql_tool。

generate_sql 最多尝试 3 次（含首次）：若 check_sql 的 syntax_ok 为 false，
或 execute_sql 的 error_message 非空，则将错误摘要写入上下文并重新调用 generate_sql_tool；
最多额外重试 2 次。

对外入口：`build_sql_pipeline`（LangChain Runnable）、`run_sql_pipeline_with_feedback`（dict + 可选逐步回调）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableLambda

from llm import get_llm
from tools.check_sql import build_check_sql_tool
from tools.execute_sql import build_execute_sql_tool
from tools.generate_sql import build_generate_sql_tool
from tools.rewrite_to_query import build_rewrite_to_query_tool

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


def _parse_check_syntax_ok(check_json: str) -> tuple[bool, str]:
    try:
        d = json.loads(check_json)
        ok = d.get("syntax_ok") is True
        brief = str(d.get("brief") or "")
        return ok, brief
    except (json.JSONDecodeError, TypeError):
        return False, "check_sql 返回非合法 JSON"


def _execute_error_message_nonempty(exec_json: str) -> tuple[bool, str]:
    try:
        d = json.loads(exec_json)
        msg = d.get("error_message")
        if msg is None:
            return False, ""
        s = str(msg).strip()
        return bool(s), s
    except (json.JSONDecodeError, TypeError):
        return True, "execute_sql 返回非合法 JSON"


def _pipeline_tools(model=None) -> tuple[Any, Any, Any, Any, Any]:
    llm = model or get_llm()
    return (
        llm,
        build_rewrite_to_query_tool(llm),
        build_generate_sql_tool(llm),
        build_check_sql_tool(),
        build_execute_sql_tool(),
    )


def _run_retry_loop(
    rewrite_json: str,
    *,
    generate_tool: Any,
    check_tool: Any,
    execute_tool: Any,
    emit: Callable[[str, str], None] | None,
) -> tuple[str, str, str, int]:
    """
    返回 (generate_sql_json, check_sql_json, execute_sql_json, attempts_used)。
    """
    feedback_lines: list[str] = []
    sql_json = ""
    check_json = ""
    exec_json = ""
    attempts_used = 0

    for _ in range(MAX_GENERATE_ATTEMPTS):
        attempts_used += 1
        ctx = "\n\n".join(feedback_lines)
        sql_json = generate_tool.invoke(
            {"rewrite_json": rewrite_json, "correction_context": ctx}
        )
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

    return sql_json, check_json, exec_json, attempts_used


def run_sql_pipeline_with_feedback(
    user_query: str | dict[str, Any],
    *,
    model=None,
    on_tool_end: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """
    跑完整条流水线；若提供 `on_tool_end(tool_name, json_str)`，则在每个工具返回后立即调用。
    """
    _, rewrite_tool, generate_tool, check_tool, execute_tool = _pipeline_tools(model)
    uq = _coerce_user_query(user_query)

    rewrite_json = rewrite_tool.invoke({"query": uq})
    if on_tool_end:
        on_tool_end("rewrite_to_query_tool", rewrite_json)

    def emit(tool_name: str, payload: str) -> None:
        if on_tool_end:
            on_tool_end(tool_name, payload)

    sql_json, check_json, exec_json, attempts_used = _run_retry_loop(
        rewrite_json,
        generate_tool=generate_tool,
        check_tool=check_tool,
        execute_tool=execute_tool,
        emit=emit,
    )

    return {
        "user_query": uq,
        "rewrite_json": rewrite_json,
        "generate_sql_json": sql_json,
        "check_sql_json": check_json,
        "execute_sql_json": exec_json,
        "generate_sql_attempts": attempts_used,
    }


def _coerce_pipeline_input(x: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(x, str):
        return {"user_query": x}
    return dict(x)


def build_sql_pipeline(model=None):
    """
    返回 Runnable：`invoke(str | {"user_query": str})` → dict，包含
    `user_query`、`rewrite_json`、`generate_sql_json`、`check_sql_json`、`execute_sql_json`、
    `generate_sql_attempts`（1–3）。

    Web 端实时进度请使用 `run_sql_pipeline_with_feedback(..., on_tool_end=...)`。
    """
    _, rewrite_tool, generate_tool, check_tool, execute_tool = _pipeline_tools(model)

    def pipeline_step(state: dict[str, Any]) -> dict[str, Any]:
        user_query = state["user_query"]
        rewrite_json = rewrite_tool.invoke({"query": user_query})

        sql_json, check_json, exec_json, attempts_used = _run_retry_loop(
            rewrite_json,
            generate_tool=generate_tool,
            check_tool=check_tool,
            execute_tool=execute_tool,
            emit=None,
        )

        return {
            "user_query": user_query,
            "rewrite_json": rewrite_json,
            "generate_sql_json": sql_json,
            "check_sql_json": check_json,
            "execute_sql_json": exec_json,
            "generate_sql_attempts": attempts_used,
        }

    return RunnableLambda(_coerce_pipeline_input) | RunnableLambda(pipeline_step)


if __name__ == "__main__":
    import sys

    question = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "2017 年 GMV 是多少？按月和各州排名的趋势怎样？"
    )

    def _emit(tool: str, payload: str) -> None:
        print(f"\n===== {tool} 完成 =====\n{payload}")

    out = run_sql_pipeline_with_feedback(question, on_tool_end=_emit)
    print(f"\n===== generate_sql 调用次数 =====\n{out.get('generate_sql_attempts')}")
