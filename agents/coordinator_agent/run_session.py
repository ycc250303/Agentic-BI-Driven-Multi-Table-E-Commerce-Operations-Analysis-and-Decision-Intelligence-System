from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agents.coordinator_agent.session_manager import CoordinatorRunOptions, SessionManager
from agents.coordinator_agent.web_events import encode_sse_event


def _write(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(str(text).encode("utf-8"))
        sys.stdout.buffer.write(b"\n")


def _write_raw(text: str) -> None:
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except UnicodeEncodeError:
        sys.stdout.buffer.write(str(text).encode("utf-8"))
        sys.stdout.buffer.flush()


def _print_sessions(items: list[dict[str, Any]]) -> None:
    if not items:
        _write("暂无 session。")
        return
    for item in items:
        _write(
            f"{item['session_id']}  turns={item['turn_count']}  "
            f"updated={item['updated_at']}  title={item['title']}"
        )


def _print_session_detail(session: dict[str, Any]) -> None:
    _write(f"Session: {session.get('session_id')}")
    _write(f"Title: {session.get('title')}")
    _write(f"Created: {session.get('created_at')}")
    _write(f"Updated: {session.get('updated_at')}")
    _write(f"Turns: {len(session.get('turns') or [])}")
    summary = str(session.get("memory_summary") or "").strip()
    if summary:
        _write("\n===== 会话摘要 =====")
        _write(summary[:1200])
    for turn in session.get("turns") or []:
        _write(f"\n===== Turn {turn.get('turn_id')} =====")
        _write(f"用户：{turn.get('user_query')}")
        resolved_task = turn.get("resolved_task") or turn.get("standalone_query")
        if resolved_task and resolved_task != turn.get("user_query"):
            _write(f"本轮任务：{resolved_task}")
        answer = str(turn.get("final_answer") or "").strip()
        if answer:
            _write(f"回答：{answer[:800]}")
        if turn.get("har_path"):
            _write(f"HAR：{turn.get('har_path')}")


def _shorten(text: str, limit: int = 120) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[: limit - 15].rstrip() + "...(truncated)"


def _print_run_result(
    result: dict[str, Any],
    *,
    trace_json: bool = False,
    sse: bool = False,
) -> None:
    if sse:
        return
    if trace_json:
        _write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    _write(f"Session: {result.get('session_id')}")
    _write(f"Turn: {result.get('turn_id')}")
    if result.get("resolved_task") != result.get("user_query"):
        _write(f"Resolved task: {result.get('resolved_task')}")

    _write("\n===== Agent 过程 =====")
    for event in result.get("trace_events") or []:
        agent = event.get("agent")
        step = event.get("step")
        summary = event.get("summary") or event.get("title")
        _write(f"[{agent}/{step}] {summary}")
        sqls = (event.get("metadata") or {}).get("sqls") or []
        for i, sql in enumerate(sqls, start=1):
            _write(f"  SQL#{i}: {sql}")

    _write("\n===== 最终回答 =====\n")
    _write(str(result.get("final_answer") or "（无 final_answer）"))
    if result.get("har_path"):
        _write(
            f"\nHAR: {result.get('har_path')} "
            f"(entries={result.get('har_entry_count', 0)})"
        )
        request_traces = result.get("http_request_traces") or []
        if request_traces:
            _write("\n===== HTTP 请求归属 =====")
            for item in request_traces:
                _write(
                    f"#{item.get('index')} [{item.get('agent')}/{item.get('step')}] "
                    f"{item.get('method')} {item.get('status')} "
                    f"{_shorten(str(item.get('url') or ''))}"
                )
    _write(f"\nSaved: {result.get('session_path')}")


def _options_from_args(args: argparse.Namespace) -> CoordinatorRunOptions:
    return CoordinatorRunOptions(
        use_llm_plan=not args.no_llm_plan,
        use_llm_viz=not args.no_llm_viz,
        use_llm_synthesize=not args.no_llm_synthesize,
        full_state=args.full_state,
    )


def _run_one(
    manager: SessionManager,
    args: argparse.Namespace,
    *,
    query: str,
    session_id: str | None,
    new_session: bool,
) -> dict[str, Any]:
    har_out = _resolve_har_out(
        manager,
        args,
        session_id=session_id,
        new_session=new_session,
    )
    if args.sse:
        last_event: dict[str, Any] = {}
        for event in manager.stream_turn_events(
            query=query,
            session_id=session_id,
            new_session=new_session,
            title=args.title or "",
            options=_options_from_args(args),
            har_out=har_out,
            har_labels_only=args.har_labels_only,
        ):
            last_event = event
            _write_raw(encode_sse_event(event))
        return {
            "session_id": last_event.get("session_id") or session_id or "",
            "turn_id": last_event.get("turn_id") or 0,
        }

    result = manager.run_turn(
        query=query,
        session_id=session_id,
        new_session=new_session,
        title=args.title or "",
        options=_options_from_args(args),
        har_out=har_out,
        har_labels_only=args.har_labels_only,
    )
    _print_run_result(result, trace_json=args.trace_json, sse=args.sse)
    return result


def _safe_path_token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value)[:80]


def _resolve_har_out(
    manager: SessionManager,
    args: argparse.Namespace,
    *,
    session_id: str | None,
    new_session: bool,
) -> Path | None:
    if not args.har_out:
        return None

    base = Path(args.har_out)
    if not args.interactive:
        return base

    if session_id and not new_session:
        try:
            turn_id = len(manager.load_session(session_id).get("turns") or []) + 1
        except Exception:
            turn_id = 0
        token = f"{_safe_path_token(session_id)}_turn{turn_id or 'next'}"
    else:
        token = "new_turn"

    if base.suffix.lower() == ".har":
        return base.with_name(f"{base.stem}_{token}{base.suffix}")
    return base / f"{token}.har"


def main() -> None:
    parser = argparse.ArgumentParser(description="Coordinator 多轮 session CLI")
    parser.add_argument("--new", action="store_true", help="新建 session")
    parser.add_argument("--session-id", help="继续指定 session")
    parser.add_argument("--title", default="", help="新 session 标题")
    parser.add_argument("--query", help="本轮用户问题")
    parser.add_argument("--interactive", action="store_true", help="进入循环对话模式")
    parser.add_argument("--list", action="store_true", help="列出已有 session")
    parser.add_argument("--show", help="展示指定 session")
    parser.add_argument("--trace-json", action="store_true", help="输出结构化 JSON")
    parser.add_argument("--sse", action="store_true", help="按 Server-Sent Events 文本格式输出本轮结果")
    parser.add_argument("--full-state", action="store_true", help="将完整 state 保存到 turn")
    parser.add_argument("--har-out", help="可选：捕获本轮 httpx 流量并写出 HAR")
    parser.add_argument(
        "--har-labels-only",
        action="store_true",
        help="仅在 HAR entry 写入 Agent 标签，不向外部 API 发送 X-Agentic-BI-* 请求头",
    )
    parser.add_argument("--no-llm-plan", action="store_true")
    parser.add_argument("--no-llm-viz", action="store_true")
    parser.add_argument("--no-llm-synthesize", action="store_true")
    args = parser.parse_args()

    manager = SessionManager()

    if args.list:
        _print_sessions(manager.list_sessions())
        return

    if args.show:
        _print_session_detail(manager.load_session(args.show))
        return

    if not args.query and not args.interactive:
        parser.error("需要 --query，或使用 --interactive / --list / --show。")

    session_id = args.session_id
    new_session = bool(args.new or not session_id)

    if args.query:
        result = _run_one(
            manager,
            args,
            query=args.query,
            session_id=session_id,
            new_session=new_session,
        )
        session_id = str(result.get("session_id") or session_id or "")
        new_session = False

    if args.interactive:
        if args.new and not session_id:
            session = manager.create_session(title=args.title or "交互会话")
            session_id = str(session["session_id"])
            _write(f"Session: {session_id}")
        _write("输入 exit / quit 结束。")
        while True:
            try:
                query = input("user> ").strip()
            except EOFError:
                break
            if query.lower() in {"exit", "quit"}:
                break
            if not query:
                continue
            result = _run_one(
                manager,
                args,
                query=query,
                session_id=session_id,
                new_session=not bool(session_id),
            )
            session_id = str(result.get("session_id") or session_id or "")


if __name__ == "__main__":
    main()
