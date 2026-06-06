from __future__ import annotations

import json
from datetime import datetime
from collections.abc import Callable
from typing import Any


TRACE_PREVIEW_CHARS = 1200


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _json_load(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return None


def _truncate(text: str, limit: int = TRACE_PREVIEW_CHARS) -> str:
    s = str(text or "")
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "...(truncated)"


def _payload_preview(payload: Any, limit: int = TRACE_PREVIEW_CHARS) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        parsed = _json_load(payload)
        if parsed is not None:
            return _truncate(json.dumps(parsed, ensure_ascii=False, indent=2), limit)
        return _truncate(payload, limit)
    return _truncate(json.dumps(payload, ensure_ascii=False, indent=2, default=str), limit)


def _extract_sqls(payload: Any) -> list[str]:
    data = payload
    if isinstance(payload, str):
        data = _json_load(payload)
    if not isinstance(data, dict):
        return []
    raw_sqls = data.get("query_sqls")
    if raw_sqls is None and isinstance(data.get("query_sql"), str):
        raw_sqls = [data.get("query_sql")]
    if not isinstance(raw_sqls, list):
        return []
    sqls: list[str] = []
    for item in raw_sqls:
        sql = str(item or "").strip()
        if sql:
            sqls.append(sql)
    return sqls


def _format_sql_list(sqls: list[str], *, limit: int = 900) -> str:
    if not sqls:
        return ""
    lines = []
    for i, sql in enumerate(sqls, start=1):
        lines.append(f"SQL#{i}: {sql}")
    return _truncate("\n".join(lines), limit)


def _tool_agent(tool_name: str) -> str:
    if tool_name.startswith("visualization"):
        return "visualization_agent"
    if tool_name in {
        "rewrite_to_query_tool",
        "validate_rewrite_plan_tool",
        "generate_sql_tool",
        "check_sql_tool",
        "execute_sql_tool",
    }:
        return "data_analysis_agent"
    if tool_name in {"review_insight_tool", "sentiment_tool", "wordcloud_tool"}:
        return "nlp_agent"
    return "coordinator_agent"


def _tool_step(tool_name: str) -> str:
    if tool_name.endswith("_tool"):
        return tool_name.removesuffix("_tool")
    return tool_name


def summarize_tool_payload(tool_name: str, payload: str) -> str:
    data = _json_load(payload)
    if not isinstance(data, dict):
        text = str(payload or "").strip().replace("\n", " ")
        return _truncate(text, 180) if text else "工具返回了非 JSON 文本。"

    if tool_name == "rewrite_to_query_tool":
        query_for_sql = str(data.get("query_for_sql") or "").strip()
        views = data.get("candidate_views") or []
        view_text = f"，候选视图 {len(views)} 个" if isinstance(views, list) else ""
        return f"完成查询意图结构化{view_text}：{_truncate(query_for_sql, 120)}"

    if tool_name == "validate_rewrite_plan_tool":
        ok = data.get("plan_ok")
        brief = str(data.get("brief") or "").strip()
        return f"语义校验 {'通过' if ok else '未通过'}：{_truncate(brief, 140)}"

    if tool_name == "generate_sql_tool":
        sqls = _extract_sqls(data)
        count = len(sqls) if sqls else 0
        explanation = str(data.get("result_explanation") or "").strip()
        return f"生成 {count} 条 SQL。{_truncate(explanation, 160)}"

    if tool_name == "check_sql_tool":
        ok = data.get("syntax_ok")
        brief = str(data.get("brief") or "").strip()
        return f"SQL 语法检查 {'通过' if ok else '未通过'}：{_truncate(brief, 160)}"

    if tool_name == "execute_sql_tool":
        ok = bool(data.get("ok"))
        results = data.get("results") or []
        if isinstance(results, list) and results:
            row_count = sum(int(item.get("row_count_returned") or 0) for item in results if isinstance(item, dict))
            return f"SQL 执行{'成功' if ok else '部分失败'}，返回 {row_count} 行结果。"
        row_count = data.get("row_count_returned")
        if row_count is not None:
            return f"SQL 执行{'成功' if ok else '失败'}，返回 {row_count} 行结果。"
        err = str(data.get("error_message") or "").strip()
        return f"SQL 执行{'成功' if ok else '失败'}。{_truncate(err, 160)}"

    if tool_name == "review_insight_tool":
        summary = str(data.get("summary") or data.get("summary_text") or "").strip()
        topics = data.get("topic_distribution") or data.get("negative_topics") or {}
        if summary:
            return _truncate(summary, 180)
        if topics:
            return "完成评论洞察，已生成差评主题/情感相关结果。"
        return "完成评论洞察。"

    if tool_name.startswith("visualization"):
        title = (
            data.get("title")
            or (data.get("plan") or {}).get("title")
            or data.get("chart_type_resolved")
            or (data.get("plan") or {}).get("chart_type")
        )
        ok = data.get("ok")
        if title:
            return f"图表{'生成成功' if ok else '生成失败'}：{title}"
        return f"可视化步骤{'完成' if ok else '未成功'}。"

    return "工具步骤完成。"


class TraceCollector:
    """Collect user-visible Agent execution events.

    This records observable tool/node outputs only. It does not expose hidden
    model reasoning or chain-of-thought.
    """

    def __init__(
        self,
        *,
        session_id: str = "",
        turn_id: int = 0,
        preview_chars: int = TRACE_PREVIEW_CHARS,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.session_id = session_id
        self.turn_id = int(turn_id)
        self.preview_chars = int(preview_chars)
        self.on_event = on_event
        self._events: list[dict[str, Any]] = []
        self._last_generated_sqls: list[str] = []

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def emit(
        self,
        *,
        agent: str,
        step: str,
        kind: str,
        title: str,
        summary: str,
        payload: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": f"turn-{self.turn_id}-{len(self._events) + 1:03d}",
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "agent": agent,
            "step": step,
            "kind": kind,
            "title": title,
            "summary": str(summary or "").strip(),
            "created_at": _now_iso(),
        }
        if payload is not None:
            event["payload_preview"] = _payload_preview(payload, self.preview_chars)
        if metadata:
            event["metadata"] = dict(metadata)
        self._events.append(event)
        if self.on_event is not None:
            try:
                self.on_event(dict(event))
            except Exception:
                pass
        return event

    def emit_tool_result(self, tool_name: str, payload: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if tool_name == "generate_sql_tool":
            sqls = _extract_sqls(payload)
            if sqls:
                self._last_generated_sqls = sqls
                metadata["sqls"] = sqls
        elif tool_name == "execute_sql_tool" and self._last_generated_sqls:
            metadata["sqls"] = list(self._last_generated_sqls)
        return self.emit(
            agent=_tool_agent(tool_name),
            step=_tool_step(tool_name),
            kind="tool_result",
            title=f"{tool_name} 完成",
            summary=summarize_tool_payload(tool_name, payload),
            payload=payload,
            metadata=metadata or None,
        )
