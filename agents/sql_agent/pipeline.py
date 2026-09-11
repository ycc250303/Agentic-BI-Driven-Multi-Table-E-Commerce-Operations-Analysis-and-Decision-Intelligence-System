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
    """解析 check 工具返回的 JSON。

    入参：check_sql_tool 的 JSON 字符串。
    返回：``(syntax_ok 是否为 True, brief)``；JSON 非法时视为未通过。
    """
    d = _json_load_dict(check_json)
    if d is None:
        return False, "check_sql 返回非合法 JSON"
    ok = d.get("syntax_ok") is True
    brief = str(d.get("brief") or "")
    return ok, brief


def _execute_error_message_nonempty(exec_json: str) -> tuple[bool, str]:
    """判断 execute 是否应触发带错重试。

    入参：execute_sql_tool 的 JSON 字符串。
    返回：``(需要重试, 错误摘要)``。JSON 非法或 ``error_message`` 非空则为需要重试。
    """
    d = _json_load_dict(exec_json)
    if d is None:
        return True, "execute_sql 返回非合法 JSON"
    msg = d.get("error_message")
    if msg is None:
        return False, ""
    s = str(msg).strip()
    return bool(s), s


def _pipeline_tools(model=None) -> tuple[Any, Any, Any, Any]:
    """装配 rewrite / generate / check / execute 四个工具。``model`` 供测试注入。"""
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
    """NL → 结构化计划。最多 ``MAX_REWRITE_ATTEMPTS`` 次。

    入参：``user_query`` 本轮自然语言；``rewrite_tool``；``emit`` 可选进度回调。
    返回：``(rewrite_json, 实际尝试次数, 失败说明列表)``。
    失败：schema/调用异常写入 correction_context 重试；全部失败则返回空计划 JSON，
    失败说明交给后续 generate 循环。
    """
    rewrite_json = ""
    attempts_used = 0
    feedback_lines: list[str] = []

    for _ in range(MAX_REWRITE_ATTEMPTS):
        attempts_used += 1
        # 上一轮 schema/调用失败摘要，供本轮纠错
        try:
            rewrite_json = rewrite_tool.invoke(
                {
                    "query": user_query,
                    "correction_context": "\n\n".join(feedback_lines),
                }
            )
        except Exception as e:
            feedback_lines.append(f"[结构化转写失败] {e}")
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
    """generate → check → execute，失败把错误写回 generate。最多 3 次（含首次）。

    入参：``rewrite_json`` 转写结果；三个工具；``emit`` 可选；``initial_feedback``
    一般为 rewrite 失败说明。
    返回：``(generate_sql_json, check_sql_json, execute_sql_json, generate 尝试次数)``。
    失败：check 未通过不连库；execute 的 ``error_message`` 非空则重试；3 次仍无成功
    execute 时填 skipped 占位，不抛给调用方。
    """
    feedback_lines: list[str] = list(initial_feedback or [])
    sql_json = ""
    check_json = ""
    exec_json = ""
    attempts_used = 0
    last_generate_error = ""

    for _ in range(MAX_GENERATE_ATTEMPTS):
        attempts_used += 1
        # 上一轮 generate/check/execute 的失败摘要，供本轮纠错
        ctx = "\n\n".join(feedback_lines)
        try:
            sql_json = generate_tool.invoke(
                {"rewrite_json": rewrite_json, "correction_context": ctx}
            )
        except Exception as e:
            last_generate_error = str(e)
            feedback_lines.append(f"[SQL 生成失败] {last_generate_error}")
            continue
        if emit:
            emit("generate_sql_tool", sql_json)

        check_json = check_tool.invoke({"generate_sql_json": sql_json})
        if emit:
            emit("check_sql_tool", check_json)

        check_ok, brief = _parse_check_syntax_ok(check_json)
        if not check_ok:
            # 格式/只读未过：不执行，brief 带回下一轮 generate
            feedback_lines.append(f"[格式与只读校验未通过] {brief}")
            continue

        exec_json = execute_tool.invoke({"generate_sql_json": sql_json})
        if emit:
            emit("execute_sql_tool", exec_json)

        has_err, err_s = _execute_error_message_nonempty(exec_json)
        if not has_err:
            break

        # 连库失败或 SQL 报错：error_message 带回下一轮 generate
        feedback_lines.append(f"[查询执行失败] {err_s}")

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
    """按 rewrite → generate/check/execute 跑通并拼对外 dict。

    入参：已规范化的 ``user_query`` 与四个工具；``on_tool_end(tool_name, json_str)``
    在每个工具返回后立刻回调（Web/SSE 进度）。
    返回：含 ``rewrite_json`` / ``generate_sql_json`` / ``check_sql_json`` /
    ``execute_sql_json`` 及各阶段尝试次数。不在此处抛业务失败。
    """

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
    """SQL Agent 对外入口：自然语言 → 只读查询结果摘要。

    入参：``user_query`` 为字符串或 ``{"user_query": str}``；``model`` 可选注入结构化
    LLM；``on_tool_end`` 可选逐步回调。
    返回：流水线 dict（JSON 字符串字段 + attempts）。协调器 / 可视化从此导入。
    失败：不抛给调用方，错误落在 ``check_sql_json`` / ``execute_sql_json``。
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
