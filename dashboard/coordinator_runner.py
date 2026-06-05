from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agents.coordinator_agent import build_coordinator_graph

from dashboard.agent_labels import SUB_AGENT_NODES, label_for
from dashboard.models import AgentProgress

_TRACKABLE_STEPS = frozenset({"decompose", *SUB_AGENT_NODES})


def _merge_state(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged.update(patch)
    return merged


def _append_step(steps: list[str], step_id: str) -> None:
    if step_id not in steps:
        steps.append(step_id)


def _build_progress(
    completed: list[str],
    current: str | None,
    *,
    finished: bool = False,
) -> AgentProgress:
    return AgentProgress(
        completed=list(completed),
        current=current,
        current_label=label_for(current),
        finished=finished,
    )


def run_with_agent_progress(
    user_query: str,
    *,
    on_progress: Callable[[AgentProgress, dict[str, Any]], None] | None = None,
    use_llm_plan: bool = True,
    use_llm_viz: bool = True,
    use_llm_synthesize: bool = True,
) -> dict[str, Any]:
    graph = build_coordinator_graph(
        use_llm_plan=use_llm_plan,
        use_llm_viz=use_llm_viz,
        use_llm_synthesize=use_llm_synthesize,
    )
    initial: dict[str, Any] = {"user_query": user_query, "question": user_query}
    final = dict(initial)
    completed_steps: list[str] = []
    current: str | None = "decompose"

    if on_progress is not None:
        on_progress(_build_progress(completed_steps, current), final)

    for chunk in graph.stream(initial, stream_mode="updates"):
        node_name, patch = next(iter(chunk.items()))
        final = _merge_state(final, patch)

        if node_name == "orchestrator":
            next_agent = str(final.get("next_agent") or "")
            if next_agent in SUB_AGENT_NODES:
                current = next_agent
            else:
                current = None
        elif node_name in _TRACKABLE_STEPS:
            _append_step(completed_steps, node_name)
            current = "orchestrator"

        if on_progress is not None:
            on_progress(_build_progress(completed_steps, current), final)

    if on_progress is not None:
        on_progress(_build_progress(completed_steps, None, finished=True), final)

    return final
