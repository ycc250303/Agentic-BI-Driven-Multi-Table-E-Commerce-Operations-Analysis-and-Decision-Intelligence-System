"""
SQL Agent 入口：用 LangChain Runnable 将流程固定为
用户自然语言 → rewrite_to_query_tool → validate_rewrite_plan_tool → generate_sql_tool
→ check_sql_tool → execute_sql_tool。

`generate_sql` 可输出多条 `query_sqls`；`execute_sql` 依次执行并为每条结果写独立 CSV。

rewrite_to_query 最多尝试 3 次（含首次）：若 validate_rewrite_plan_tool 的 plan_ok 为 false，
则将语义校验反馈写入 correction_context 重新调用 rewrite_to_query_tool。

generate_sql 最多尝试 3 次（含首次）：若 check_sql 的 syntax_ok 为 false，或 execute_sql 的
error_message 非空，则将错误摘要写入上下文并重新调用 generate_sql_tool；最多额外重试 2 次。

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
from tools.validate_rewrite_plan import build_validate_rewrite_plan_tool

MAX_REWRITE_ATTEMPTS = 3
MAX_GENERATE_ATTEMPTS = 3
TOOL_MODEL_RETRIES = 1

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


def _parse_plan_ok(validate_json: str) -> tuple[bool, str]:
    d = _json_load_dict(validate_json)
    if d is None:
        return False, "validate_rewrite_plan_tool 返回非合法 JSON"
    ok = d.get("plan_ok") is True
    brief = str(d.get("brief") or "")
    return ok, brief


def _pipeline_tools(model=None) -> tuple[Any, Any, Any, Any, Any, Any]:
    llm = model or get_llm()
    return (
        llm,
        build_rewrite_to_query_tool(llm, max_retries=TOOL_MODEL_RETRIES),
        build_validate_rewrite_plan_tool(),
        build_generate_sql_tool(llm, max_retries=TOOL_MODEL_RETRIES),
        build_check_sql_tool(),
        build_execute_sql_tool(),
    )


def _run_rewrite_with_validation(
    user_query: str,
    *,
    rewrite_tool: Any,
    validate_tool: Any,
    emit: Callable[[str, str], None] | None,
) -> tuple[str, str, int, list[str]]:
    rewrite_json = ""
    validate_json = ""
    attempts_used = 0
    feedback_lines: list[str] = []
    last_rewrite_error = ""

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
            last_rewrite_error = str(e)
            feedback_lines.append(f"[rewrite_to_query 失败] {last_rewrite_error}")
            continue
        if emit:
            emit("rewrite_to_query_tool", rewrite_json)

        validate_json = validate_tool.invoke(
            {"user_query": user_query, "rewrite_json": rewrite_json}
        )
        if emit:
            emit("validate_rewrite_plan_tool", validate_json)

        ok, brief = _parse_plan_ok(validate_json)
        if ok:
            return rewrite_json, validate_json, attempts_used, []
        feedback_lines.append(f"[validate_rewrite_plan 未通过] {brief}")

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
    if not validate_json.strip():
        msg = (
            "rewrite_to_query_tool 连续失败，未获得可校验计划。"
            + (f" 最近错误：{last_rewrite_error}" if last_rewrite_error else "")
        )
        validate_json = json.dumps({"plan_ok": False, "brief": msg}, ensure_ascii=False)

    return rewrite_json, validate_json, attempts_used, feedback_lines


def _run_retry_loop(
    rewrite_json: str,
    *,
    generate_tool: Any,
    check_tool: Any,
    execute_tool: Any,
    emit: Callable[[str, str], None] | None,
    initial_feedback: list[str] | None = None,
) -> tuple[str, str, str, int]:
    """
    返回 (generate_sql_json, check_sql_json, execute_sql_json, attempts_used)。
    """
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


def run_sql_pipeline_with_feedback(
    user_query: str | dict[str, Any],
    *,
    model=None,
    on_tool_end: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """
    跑完整条流水线；若提供 `on_tool_end(tool_name, json_str)`，则在每个工具返回后立即调用。
    """
    (
        _,
        rewrite_tool,
        validate_tool,
        generate_tool,
        check_tool,
        execute_tool,
    ) = _pipeline_tools(model)
    uq = _coerce_user_query(user_query)

    def emit(tool_name: str, payload: str) -> None:
        if on_tool_end:
            on_tool_end(tool_name, payload)

    rewrite_json, validate_json, rewrite_attempts, rewrite_feedback = (
        _run_rewrite_with_validation(
            uq,
            rewrite_tool=rewrite_tool,
            validate_tool=validate_tool,
            emit=emit,
        )
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
        "user_query": uq,
        "rewrite_json": rewrite_json,
        "validate_rewrite_json": validate_json,
        "rewrite_attempts": rewrite_attempts,
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
    `user_query`、`rewrite_json`、`validate_rewrite_json`、`rewrite_attempts`、
    `generate_sql_json`、`check_sql_json`、`execute_sql_json`、`generate_sql_attempts`。

    Web 端实时进度请使用 `run_sql_pipeline_with_feedback(..., on_tool_end=...)`。
    """
    (
        _,
        rewrite_tool,
        validate_tool,
        generate_tool,
        check_tool,
        execute_tool,
    ) = _pipeline_tools(model)

    def pipeline_step(state: dict[str, Any]) -> dict[str, Any]:
        user_query = state["user_query"]
        rewrite_json, validate_json, rewrite_attempts, rewrite_feedback = (
            _run_rewrite_with_validation(
                user_query,
                rewrite_tool=rewrite_tool,
                validate_tool=validate_tool,
                emit=None,
            )
        )

        sql_json, check_json, exec_json, attempts_used = _run_retry_loop(
            rewrite_json,
            generate_tool=generate_tool,
            check_tool=check_tool,
            execute_tool=execute_tool,
            emit=None,
            initial_feedback=rewrite_feedback,
        )

        return {
            "user_query": user_query,
            "rewrite_json": rewrite_json,
            "validate_rewrite_json": validate_json,
            "rewrite_attempts": rewrite_attempts,
            "generate_sql_json": sql_json,
            "check_sql_json": check_json,
            "execute_sql_json": exec_json,
            "generate_sql_attempts": attempts_used,
        }

    return RunnableLambda(_coerce_pipeline_input) | RunnableLambda(pipeline_step)


if __name__ == "__main__":
    import sys

    TEST_QUESTIONS = [
        "2017 年 GMV 是多少？按月和各州排名的趋势怎样？",
        "平台整体准时交付率是多少？哪些州延迟最严重？",
        "哪种支付方式最受欢迎？平均分期数是多少？",
        "产品的重量、尺寸与运费之间有什么关系？",
        "Top 10 差评品类是什么？",
        "2017年哪个州的销售额最高？交付准时率是多少？哪种支付方式最受欢迎？",
        "哪些卖家的差评率最高？",
    ]

    questions = [sys.argv[1]] if len(sys.argv) > 1 else TEST_QUESTIONS

    def _emit(tool: str, payload: str) -> None:
        print(f"\n===== {tool} 完成 =====\n{payload}")

    for i, question in enumerate(questions, start=1):
        print(f"\n{'=' * 60}\n测试问题 {i}/{len(questions)}\n{question}\n{'=' * 60}")
        out = run_sql_pipeline_with_feedback(question, on_tool_end=_emit)
        print(f"\n===== rewrite_to_query 调用次数 =====\n{out.get('rewrite_attempts')}")
        print(f"\n===== generate_sql 调用次数 =====\n{out.get('generate_sql_attempts')}")
