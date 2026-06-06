from __future__ import annotations

import json
from typing import Any, Iterable


WEB_EVENT_SCHEMA_VERSION = "1.0"


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _event(
    *,
    event_type: str,
    event_id: str,
    session_id: str,
    turn_id: int,
    sequence: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": WEB_EVENT_SCHEMA_VERSION,
        "type": event_type,
        "id": event_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "sequence": sequence,
        "data": _jsonable(data),
    }


def make_turn_started_event(
    *,
    session_id: str,
    turn_id: int,
    sequence: int,
    user_query: str,
    standalone_query: str,
    resolved_task: str | None = None,
) -> dict[str, Any]:
    task = resolved_task if resolved_task is not None else standalone_query
    return _event(
        event_type="turn.started",
        event_id=f"{session_id}:{turn_id}:started",
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        data={
            "user_query": user_query,
            "standalone_query": standalone_query,
            "resolved_task": task,
        },
    )


def make_trace_event(
    *,
    trace: dict[str, Any],
    session_id: str,
    turn_id: int,
    sequence: int,
) -> dict[str, Any]:
    trace_id = str(trace.get("event_id") or f"trace-{sequence}")
    return _event(
        event_type="trace.event",
        event_id=f"{session_id}:{turn_id}:{trace_id}",
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        data={"trace": trace},
    )


def make_answer_final_event(
    *,
    result: dict[str, Any],
    session_id: str,
    turn_id: int,
    sequence: int,
) -> dict[str, Any]:
    return _event(
        event_type="answer.final",
        event_id=f"{session_id}:{turn_id}:answer",
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        data={"final_answer": result.get("final_answer") or ""},
    )


def make_har_saved_event(
    *,
    result: dict[str, Any],
    session_id: str,
    turn_id: int,
    sequence: int,
) -> dict[str, Any]:
    return _event(
        event_type="har.saved",
        event_id=f"{session_id}:{turn_id}:har",
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        data={
            "har_path": result.get("har_path"),
            "har_entry_count": int(result.get("har_entry_count") or 0),
        },
    )


def make_turn_completed_event(
    *,
    result: dict[str, Any],
    session_id: str,
    turn_id: int,
    sequence: int,
) -> dict[str, Any]:
    return _event(
        event_type="turn.completed",
        event_id=f"{session_id}:{turn_id}:completed",
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        data={
            "session_path": result.get("session_path") or "",
            "state_summary": result.get("state_summary") or {},
        },
    )


def make_turn_error_event(
    *,
    session_id: str,
    turn_id: int,
    sequence: int,
    error: BaseException,
) -> dict[str, Any]:
    return _event(
        event_type="turn.error",
        event_id=f"{session_id}:{turn_id}:error",
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        data={
            "error_type": type(error).__name__,
            "message": str(error),
        },
    )


def iter_web_events(result: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Convert one SessionManager.run_turn result into Web/SSE friendly events.

    This is the completed-turn conversion path. For live UI updates, use
    SessionManager.stream_turn_events(), which emits the same event shape while
    the Agent run is still in progress.
    """
    session_id = str(result.get("session_id") or "")
    turn_id = int(result.get("turn_id") or 0)
    sequence = 1

    yield make_turn_started_event(
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        user_query=result.get("user_query") or "",
        standalone_query=result.get("standalone_query") or "",
        resolved_task=result.get("resolved_task") or result.get("standalone_query") or "",
    )
    sequence += 1

    for trace in result.get("trace_events") or []:
        yield make_trace_event(
            trace=trace,
            session_id=session_id,
            turn_id=turn_id,
            sequence=sequence,
        )
        sequence += 1

    yield make_answer_final_event(
        result=result,
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
    )
    sequence += 1

    if result.get("har_path"):
        yield make_har_saved_event(
            result=result,
            session_id=session_id,
            turn_id=turn_id,
            sequence=sequence,
        )
        sequence += 1

    yield make_turn_completed_event(
        result=result,
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
    )


def web_events_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    return list(iter_web_events(result))


def encode_sse_event(event: dict[str, Any]) -> str:
    """Encode a web event dict as one Server-Sent Events message."""
    event_type = str(event.get("type") or "message")
    event_id = str(event.get("id") or "")
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
    lines = [f"event: {event_type}"]
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"


def encode_sse_events(events: Iterable[dict[str, Any]]) -> str:
    return "".join(encode_sse_event(event) for event in events)


def result_to_sse(result: dict[str, Any]) -> str:
    return encode_sse_events(iter_web_events(result))
