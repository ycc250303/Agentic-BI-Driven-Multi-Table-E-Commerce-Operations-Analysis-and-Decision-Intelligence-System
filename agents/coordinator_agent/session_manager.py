from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from agents.coordinator_agent.har_capture import (
    HttpxHarCapture,
    count_har_entries_by_agent,
    summarize_har_entries,
)
from agents.coordinator_agent.memory import (
    build_conversation_history,
    build_state_summary,
    update_memory_summary,
)
from agents.coordinator_agent.conversation_resolver import resolve_conversation_context
from agents.coordinator_agent.session_store import LocalSessionStore
from agents.coordinator_agent.tracing import TraceCollector


@dataclass(frozen=True)
class CoordinatorRunOptions:
    use_llm_plan: bool = True
    use_llm_viz: bool = True
    use_llm_synthesize: bool = True
    full_state: bool = False


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _infer_title(query: str) -> str:
    q = str(query or "").strip()
    if not q:
        return "未命名会话"
    return q[:40]


_PLACEHOLDER_TITLES = frozenset({"", "新对话", "新会话", "未命名会话"})


def _should_infer_title_from_first_query(session: dict[str, Any], *, turn_id: int) -> bool:
    """首轮提问后，若标题仍为占位符（如 Dashboard 预置的「新对话」），则用问题生成标题。"""
    if turn_id != 1:
        return False
    title = str(session.get("title") or "").strip()
    if not title:
        return True
    if title in _PLACEHOLDER_TITLES:
        return True
    return title == str(session.get("session_id") or "").strip()


class SessionManager:
    """Manage multi-turn Coordinator sessions."""

    def __init__(self, store: LocalSessionStore | None = None) -> None:
        self.store = store or LocalSessionStore()

    def create_session(self, *, title: str = "") -> dict[str, Any]:
        session = self.store.create_session(title=title)
        self.store.save_session(session)
        return session

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.store.list_sessions()

    def load_session(self, session_id: str) -> dict[str, Any]:
        return self.store.load_session(session_id)

    def delete_session(self, session_id: str) -> None:
        self.store.delete_session(session_id)

    def run_turn(
        self,
        *,
        query: str,
        session_id: str | None = None,
        new_session: bool = False,
        title: str = "",
        options: CoordinatorRunOptions | None = None,
        model=None,
        har_out: Path | str | None = None,
        har_labels_only: bool = False,
        trace_event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if har_out is None:
            return self._run_turn_body(
                query=query,
                session_id=session_id,
                new_session=new_session,
                title=title,
                options=options,
                model=model,
                har_out=None,
                trace_event_callback=trace_event_callback,
            )

        with HttpxHarCapture(
            har_out,
            send_trace_headers=not har_labels_only,
        ) as capture:
            result = self._run_turn_body(
                query=query,
                session_id=session_id,
                new_session=new_session,
                title=title,
                options=options,
                model=model,
                har_out=har_out,
                trace_event_callback=trace_event_callback,
            )
        result["har_path"] = str(Path(har_out))
        result["har_entry_count"] = len(capture.entries)
        result["http_request_traces"] = summarize_har_entries(capture.entries)
        result["har_agent_counts"] = count_har_entries_by_agent(capture.entries)
        return result

    def _run_turn_body(
        self,
        *,
        query: str,
        session_id: str | None = None,
        new_session: bool = False,
        title: str = "",
        options: CoordinatorRunOptions | None = None,
        model=None,
        har_out: Path | str | None = None,
        trace_event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not str(query or "").strip():
            raise ValueError("query 不能为空")

        opts = options or CoordinatorRunOptions()
        if new_session or not session_id:
            session = self.store.create_session(title=title or _infer_title(query))
        else:
            session = self.store.load_session(session_id)

        turn_id = len(session.get("turns") or []) + 1
        history = build_conversation_history(session)
        trace = TraceCollector(
            session_id=str(session.get("session_id") or ""),
            turn_id=turn_id,
            on_event=trace_event_callback,
        )
        resolution = resolve_conversation_context(query, session, model=model)
        resolved_task = str(resolution.get("resolved_task") or "").strip()
        needs_clarification = bool(resolution.get("needs_clarification"))
        trace.emit(
            agent="session_manager",
            step="resolve_conversation_context",
            kind="session",
            title="会话语义理解完成",
            summary=(
                str(resolution.get("clarification_question") or "")
                if needs_clarification
                else (
                    "本轮是新任务或自足问题，按用户原意执行。"
                    if resolved_task == query
                    else f"已明确本轮真实任务：{resolved_task}"
                )
            ),
            metadata={
                "user_query": query,
                "resolved_task": resolved_task,
                "standalone_query": resolved_task,
                "relation_to_previous": resolution.get("relation_to_previous"),
                "context_used": resolution.get("context_used"),
                "carried_over_goal": resolution.get("carried_over_goal"),
                "carried_over_subject": resolution.get("carried_over_subject"),
                "new_constraints": resolution.get("new_constraints") or [],
                "changed_constraints": resolution.get("changed_constraints") or [],
                "needs_clarification": needs_clarification,
                "confidence": resolution.get("confidence"),
            },
        )

        state: dict[str, Any] = {}
        if needs_clarification:
            final_answer = str(resolution.get("clarification_question") or "").strip()
            trace.emit(
                agent="session_manager",
                step="request_clarification",
                kind="final_answer",
                title="需要用户澄清",
                summary=final_answer,
            )
            state_summary = {
                "intent": "clarification",
                "sub_questions": [],
                "suggested_agents": [],
                "agents_done": {"session_manager": True},
                "execution_log": [],
                "warnings": [],
                "off_topic": False,
                "chart_count": 0,
                "sql_run_count": 0,
            }
        else:
            from agents.coordinator_agent.graph import run_coordinator

            state = run_coordinator(
                resolved_task,
                model=model,
                use_llm_plan=opts.use_llm_plan,
                use_llm_viz=opts.use_llm_viz,
                use_llm_synthesize=opts.use_llm_synthesize,
                conversation_history=history,
                trace_collector=trace,
            )
            final_answer = str(state.get("final_answer") or "")
            state_summary = build_state_summary(state)

        trace.emit(
            agent="session_manager",
            step="prepare_save_turn",
            kind="session",
            title="本轮会话准备保存",
            summary=f"已完成第 {turn_id} 轮回答，准备更新会话记忆。",
        )

        turn: dict[str, Any] = {
            "turn_id": turn_id,
            "created_at": trace.events[0]["created_at"] if trace.events else "",
            "user_query": query,
            "resolved_task": resolved_task,
            "standalone_query": resolved_task,
            "conversation_resolution": resolution,
            "final_answer": final_answer,
            "trace_events": trace.events,
            "state_summary": state_summary,
        }
        if opts.full_state:
            turn["state"] = _jsonable(state)
        if har_out is not None:
            turn["har_path"] = str(Path(har_out))

        session.setdefault("turns", []).append(turn)
        if _should_infer_title_from_first_query(session, turn_id=turn_id) or not session.get("title"):
            session["title"] = _infer_title(query)
        session["memory_summary"] = update_memory_summary(session, model=model)
        trace.emit(
            agent="session_manager",
            step="update_memory_summary",
            kind="session",
            title="会话记忆已更新",
            summary=str(session.get("memory_summary") or "")[:500],
        )
        trace.emit(
            agent="session_manager",
            step="save_turn",
            kind="session",
            title="本轮会话已保存",
            summary=f"保存第 {turn_id} 轮问答与 {len(trace.events) + 1} 条过程事件。",
        )
        turn["trace_events"] = trace.events
        saved_path = self.store.save_session(session)

        return {
            "session_id": session["session_id"],
            "turn_id": turn_id,
            "session_path": str(Path(saved_path)),
            "user_query": query,
            "resolved_task": resolved_task,
            "standalone_query": resolved_task,
            "conversation_resolution": resolution,
            "final_answer": final_answer,
            "trace_events": trace.events,
            "state_summary": turn["state_summary"],
            "har_path": str(Path(har_out)) if har_out is not None else "",
            "har_entry_count": 0,
            "http_request_traces": [],
            "har_agent_counts": {},
        }

    def stream_turn_events(
        self,
        *,
        query: str,
        session_id: str | None = None,
        new_session: bool = False,
        title: str = "",
        options: CoordinatorRunOptions | None = None,
        model=None,
        har_out: Path | str | None = None,
        har_labels_only: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Yield Web/SSE-friendly events while a turn is running.

        This is a synchronous generator backed by a worker thread. The worker
        runs the normal blocking Agent flow, while trace callbacks are pushed to
        a queue and yielded immediately by this generator.
        """
        from agents.coordinator_agent.web_events import (
            make_answer_final_event,
            make_har_saved_event,
            make_trace_event,
            make_turn_completed_event,
            make_turn_error_event,
            make_turn_started_event,
        )

        event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

        def on_trace(trace: dict[str, Any]) -> None:
            event_queue.put(("trace", trace))

        def worker() -> None:
            try:
                result = self.run_turn(
                    query=query,
                    session_id=session_id,
                    new_session=new_session,
                    title=title,
                    options=options,
                    model=model,
                    har_out=har_out,
                    har_labels_only=har_labels_only,
                    trace_event_callback=on_trace,
                )
                event_queue.put(("result", result))
            except Exception as e:  # noqa: BLE001
                event_queue.put(("error", e))
            finally:
                event_queue.put(("done", None))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        sequence = 1
        started = False
        active_session_id = str(session_id or "")
        active_turn_id = 0
        pending_error: BaseException | None = None

        while True:
            kind, payload = event_queue.get()
            if kind == "trace":
                trace = dict(payload)
                active_session_id = str(trace.get("session_id") or active_session_id)
                active_turn_id = int(trace.get("turn_id") or active_turn_id or 0)
                if not started:
                    metadata = trace.get("metadata") or {}
                    yield make_turn_started_event(
                        session_id=active_session_id,
                        turn_id=active_turn_id,
                        sequence=sequence,
                        user_query=str(metadata.get("user_query") or query),
                        standalone_query=str(metadata.get("standalone_query") or query),
                        resolved_task=str(metadata.get("resolved_task") or metadata.get("standalone_query") or query),
                    )
                    sequence += 1
                    started = True
                yield make_trace_event(
                    trace=trace,
                    session_id=active_session_id,
                    turn_id=active_turn_id,
                    sequence=sequence,
                )
                sequence += 1
                continue

            if kind == "result":
                result = dict(payload)
                active_session_id = str(result.get("session_id") or active_session_id)
                active_turn_id = int(result.get("turn_id") or active_turn_id or 0)
                if not started:
                    yield make_turn_started_event(
                        session_id=active_session_id,
                        turn_id=active_turn_id,
                        sequence=sequence,
                        user_query=str(result.get("user_query") or query),
                        standalone_query=str(result.get("standalone_query") or query),
                        resolved_task=str(result.get("resolved_task") or result.get("standalone_query") or query),
                    )
                    sequence += 1
                    started = True
                yield make_answer_final_event(
                    result=result,
                    session_id=active_session_id,
                    turn_id=active_turn_id,
                    sequence=sequence,
                )
                sequence += 1
                if result.get("har_path"):
                    yield make_har_saved_event(
                        result=result,
                        session_id=active_session_id,
                        turn_id=active_turn_id,
                        sequence=sequence,
                    )
                    sequence += 1
                yield make_turn_completed_event(
                    result=result,
                    session_id=active_session_id,
                    turn_id=active_turn_id,
                    sequence=sequence,
                )
                sequence += 1
                continue

            if kind == "error":
                pending_error = payload
                if not started:
                    yield make_turn_started_event(
                        session_id=active_session_id,
                        turn_id=active_turn_id,
                        sequence=sequence,
                        user_query=query,
                        standalone_query=query,
                        resolved_task=query,
                    )
                    sequence += 1
                    started = True
                yield make_turn_error_event(
                    session_id=active_session_id,
                    turn_id=active_turn_id,
                    sequence=sequence,
                    error=pending_error,
                )
                sequence += 1
                continue

            if kind == "done":
                break

        thread.join()
