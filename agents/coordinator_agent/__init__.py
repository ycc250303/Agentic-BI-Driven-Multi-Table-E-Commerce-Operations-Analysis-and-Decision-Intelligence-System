"""协调器 Agent：解析用户问题、规划多 Agent 流程、汇总最终回答。"""

from __future__ import annotations

from typing import Any


__all__ = ["AgentState", "SessionManager", "build_coordinator_graph", "run_coordinator"]


def __getattr__(name: str) -> Any:
    if name == "AgentState":
        from .state import AgentState

        return AgentState
    if name == "SessionManager":
        from .session_manager import SessionManager

        return SessionManager
    if name in {"build_coordinator_graph", "run_coordinator"}:
        from .graph import build_coordinator_graph, run_coordinator

        return {
            "build_coordinator_graph": build_coordinator_graph,
            "run_coordinator": run_coordinator,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
