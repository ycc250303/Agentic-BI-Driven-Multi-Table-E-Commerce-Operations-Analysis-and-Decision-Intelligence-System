from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx


HAR_VERSION = "1.2"
CREATOR = {
    "name": "agentic-bi-httpx-har-capture",
    "version": "1.2",
}

TRACE_AGENT_HEADER = "X-Agentic-BI-Agent"
TRACE_STEP_HEADER = "X-Agentic-BI-Step"
TRACE_LABEL_HEADER = "X-Agentic-BI-Label"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _headers_to_har(headers: httpx.Headers, *, redact_auth: bool = True) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for name, value in headers.multi_items():
        if redact_auth and name.lower() in {"authorization", "api-key", "x-api-key"}:
            value = "<redacted>"
        out.append({"name": name, "value": value})
    return out


def _decode_body(content: bytes, headers: httpx.Headers) -> tuple[str, str, str]:
    mime_type = headers.get("content-type", "")
    if not content:
        return "", mime_type, ""
    if mime_type.startswith("text/") or any(
        token in mime_type for token in ("json", "xml", "javascript", "x-www-form-urlencoded")
    ):
        encoding = "utf-8" if "json" in mime_type else (headers.encoding or "utf-8")
        return content.decode(encoding, errors="replace"), mime_type, ""
    return base64.b64encode(content).decode("ascii"), mime_type, "base64"


def _query_to_har(url: httpx.URL) -> list[dict[str, str]]:
    return [{"name": k, "value": v} for k, v in url.params.multi_items()]


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def infer_agent_trace(request_content: bytes, request: httpx.Request) -> dict[str, str]:
    """Infer the logical Agentic BI stage from OpenAI-compatible chat payloads."""
    trace = {
        "agent": "external_http",
        "step": "unknown",
        "label": "external_http.unknown",
        "source": "default",
    }
    if "chat/completions" not in str(request.url):
        return trace

    try:
        payload = json.loads(request_content.decode("utf-8"))
    except Exception:
        trace.update(
            {
                "agent": "llm",
                "step": "chat_completion",
                "label": "llm.chat_completion",
                "source": "url",
            }
        )
        return trace

    messages = payload.get("messages") or []
    all_text = "\n".join(_message_text(m) for m in messages if isinstance(m, dict))
    if "会话语义解析器" in all_text or "resolve_conversation_context" in all_text:
        trace.update(
            {
                "agent": "session_manager",
                "step": "resolve_conversation_context",
                "label": "session_manager.resolve_conversation_context",
                "source": "prompt_heuristic",
            }
        )
        return trace
    if "会话记忆摘要器" in all_text or "memory_summary" in all_text:
        trace.update(
            {
                "agent": "session_manager",
                "step": "summarize_session_memory",
                "label": "session_manager.summarize_session_memory",
                "source": "prompt_heuristic",
            }
        )
        return trace
    if "迭代路由" in all_text:
        trace.update(
            {
                "agent": "coordinator_agent",
                "step": "route_next",
                "label": "coordinator_agent.route_next",
                "source": "prompt_heuristic",
            }
        )
        return trace
    if "问题分解" in all_text and "suggested_agents" in all_text:
        trace.update(
            {
                "agent": "coordinator_agent",
                "step": "decompose_query",
                "label": "coordinator_agent.decompose_query",
                "source": "prompt_heuristic",
            }
        )
        return trace
    if "结果撰写" in all_text or "请撰写面向业务人员的最终回答" in all_text:
        trace.update(
            {
                "agent": "coordinator_agent",
                "step": "synthesize_answer",
                "label": "coordinator_agent.synthesize_answer",
                "source": "prompt_heuristic",
            }
        )
        return trace
    if "查询意图转写与结构化计划器" in all_text or "rewrite_to_query_tool 系统提示词" in all_text:
        trace.update(
            {
                "agent": "data_analysis_agent",
                "step": "rewrite_to_query",
                "label": "data_analysis_agent.rewrite_to_query",
                "source": "prompt_heuristic",
            }
        )
        return trace
    if "SQL 生成工具" in all_text and "query_sqls" in all_text:
        trace.update(
            {
                "agent": "data_analysis_agent",
                "step": "generate_sql",
                "label": "data_analysis_agent.generate_sql",
                "source": "prompt_heuristic",
            }
        )
        return trace
    if "可视化规划器" in all_text or "可视化套件规划" in all_text:
        trace.update(
            {
                "agent": "visualization_agent",
                "step": "plan_viz_suite",
                "label": "visualization_agent.plan_viz_suite",
                "source": "prompt_heuristic",
            }
        )
        return trace
    if "Decision-Agent" in all_text and ("Evidence Bundle" in all_text or "业务建议" in all_text):
        trace.update(
            {
                "agent": "decision_agent",
                "step": "compose_final_answer",
                "label": "decision_agent.compose_final_answer",
                "source": "prompt_heuristic",
            }
        )
        return trace

    trace.update(
        {
            "agent": "llm",
            "step": "chat_completion",
            "label": "llm.chat_completion",
            "source": "fallback",
        }
    )
    return trace


def _apply_trace_headers(request: httpx.Request, trace: dict[str, str]) -> None:
    request.headers[TRACE_AGENT_HEADER] = trace["agent"]
    request.headers[TRACE_STEP_HEADER] = trace["step"]
    request.headers[TRACE_LABEL_HEADER] = trace["label"]


def _request_body_to_har(request: httpx.Request, content: bytes) -> dict[str, Any] | None:
    if not content:
        return None
    text, mime_type, encoding = _decode_body(content, request.headers)
    post_data: dict[str, Any] = {"mimeType": mime_type, "text": text}
    if encoding:
        post_data["encoding"] = encoding
    return post_data


def _response_content_to_har(response: httpx.Response, content: bytes) -> dict[str, Any]:
    text, mime_type, encoding = _decode_body(content, response.headers)
    out: dict[str, Any] = {
        "size": len(content),
        "mimeType": mime_type,
        "text": text,
    }
    if encoding:
        out["encoding"] = encoding
    return out


def _build_entry(
    *,
    request: httpx.Request,
    request_content: bytes,
    response: httpx.Response,
    response_content: bytes,
    started_at: str,
    elapsed_ms: float,
    trace: dict[str, str],
) -> dict[str, Any]:
    post_data = _request_body_to_har(request, request_content)
    req: dict[str, Any] = {
        "method": request.method,
        "url": str(request.url),
        "httpVersion": "HTTP/1.1",
        "cookies": [],
        "headers": _headers_to_har(request.headers),
        "queryString": _query_to_har(request.url),
        "headersSize": -1,
        "bodySize": len(request_content),
    }
    if post_data is not None:
        req["postData"] = post_data

    resp = {
        "status": response.status_code,
        "statusText": response.reason_phrase,
        "httpVersion": "HTTP/1.1",
        "cookies": [],
        "headers": _headers_to_har(response.headers, redact_auth=False),
        "content": _response_content_to_har(response, response_content),
        "redirectURL": response.headers.get("location", ""),
        "headersSize": -1,
        "bodySize": len(response_content),
    }

    return {
        "startedDateTime": started_at,
        "time": elapsed_ms,
        "request": req,
        "response": resp,
        "cache": {},
        "timings": {
            "blocked": -1,
            "dns": -1,
            "connect": -1,
            "ssl": -1,
            "send": -1,
            "wait": elapsed_ms,
            "receive": 0,
        },
        "_agentic_bi": trace,
        "comment": trace["label"],
    }


def build_har(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "log": {
            "version": HAR_VERSION,
            "creator": CREATOR,
            "pages": [],
            "entries": entries,
        }
    }


def summarize_har_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return compact HTTP request ownership data for API/Web clients."""
    out: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        trace = entry.get("_agentic_bi") or {}
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        out.append(
            {
                "index": index,
                "agent": str(trace.get("agent") or "external_http"),
                "step": str(trace.get("step") or "unknown"),
                "label": str(trace.get("label") or ""),
                "source": str(trace.get("source") or ""),
                "method": str(request.get("method") or ""),
                "url": str(request.get("url") or ""),
                "status": response.get("status"),
                "started_at": str(entry.get("startedDateTime") or ""),
                "time_ms": entry.get("time"),
            }
        )
    return out


def count_har_entries_by_agent(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in summarize_har_entries(entries):
        agent = str(item.get("agent") or "external_http")
        counts[agent] = counts.get(agent, 0) + 1
    return counts


def write_har(path: Path | str, entries: list[dict[str, Any]]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_har(entries), ensure_ascii=False, indent=2), encoding="utf-8")
    return out


class HttpxHarCapture:
    """Context manager that captures httpx traffic as HAR and restores patches."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        send_trace_headers: bool = True,
    ) -> None:
        self.path = Path(path) if path is not None else None
        self.send_trace_headers = send_trace_headers
        self.entries: list[dict[str, Any]] = []
        self._original_sync = None
        self._original_async = None
        self._installed = False

    def __enter__(self) -> HttpxHarCapture:
        self.install()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.uninstall()
        if self.path is not None:
            self.write(self.path)

    def install(self) -> None:
        if self._installed:
            return
        self._original_sync = httpx.HTTPTransport.handle_request
        self._original_async = httpx.AsyncHTTPTransport.handle_async_request

        capture = self
        original_sync = self._original_sync
        original_async = self._original_async

        def sync_handle(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
            started_at = _now_iso()
            t0 = time.perf_counter()
            try:
                request_content = request.read()
            except Exception:
                request_content = b""
            trace = infer_agent_trace(request_content, request)
            if capture.send_trace_headers:
                _apply_trace_headers(request, trace)
            response = original_sync(self, request)
            response_content = response.read()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            capture.entries.append(
                _build_entry(
                    request=request,
                    request_content=request_content,
                    response=response,
                    response_content=response_content,
                    started_at=started_at,
                    elapsed_ms=elapsed_ms,
                    trace=trace,
                )
            )
            return response

        async def async_handle(
            self: httpx.AsyncHTTPTransport,
            request: httpx.Request,
        ) -> httpx.Response:
            started_at = _now_iso()
            t0 = time.perf_counter()
            try:
                request_content = await request.aread()
            except Exception:
                request_content = b""
            trace = infer_agent_trace(request_content, request)
            if capture.send_trace_headers:
                _apply_trace_headers(request, trace)
            response = await original_async(self, request)
            response_content = await response.aread()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            capture.entries.append(
                _build_entry(
                    request=request,
                    request_content=request_content,
                    response=response,
                    response_content=response_content,
                    started_at=started_at,
                    elapsed_ms=elapsed_ms,
                    trace=trace,
                )
            )
            return response

        httpx.HTTPTransport.handle_request = sync_handle
        httpx.AsyncHTTPTransport.handle_async_request = async_handle
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        if self._original_sync is not None:
            httpx.HTTPTransport.handle_request = self._original_sync
        if self._original_async is not None:
            httpx.AsyncHTTPTransport.handle_async_request = self._original_async
        self._installed = False

    def write(self, path: Path | str | None = None) -> Path:
        out = Path(path) if path is not None else self.path
        if out is None:
            raise ValueError("未指定 HAR 输出路径。")
        return write_har(out, self.entries)


def install_httpx_har_capture(
    entries: list[dict[str, Any]],
    *,
    send_trace_headers: bool = True,
) -> None:
    """Backward-compatible install function for the legacy misc script."""
    capture = HttpxHarCapture(send_trace_headers=send_trace_headers)
    capture.entries = entries
    capture.install()
