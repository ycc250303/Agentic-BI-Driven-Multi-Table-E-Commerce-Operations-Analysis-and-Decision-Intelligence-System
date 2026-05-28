"""Public exports for Decision-Agent.

Preferred entrypoints:
- `answer_decision`
- `run_decision`
- `run_decision_state`

Compatibility exports remain available for legacy orchestrator-style usage.
"""

__all__ = [
    "DecisionInputs",
    "DecisionResult",
    "answer_decision",
    "run_decision",
    "run_decision_state",
    "DecisionAgent",
    "decision_node",
    "build_decision_node",
    "normalize_state",
]


def __getattr__(name: str):
    if name in __all__:
        from .adapters import normalize_state
        from .langgraph_node import build_decision_node
        from .schemas import DecisionInputs, DecisionResult
        from .run import DecisionAgent, decision_node, run_decision_state
        from .service import answer_decision, run_decision

        return {
            "DecisionAgent": DecisionAgent,
            "DecisionInputs": DecisionInputs,
            "DecisionResult": DecisionResult,
            "answer_decision": answer_decision,
            "run_decision": run_decision,
            "run_decision_state": run_decision_state,
            "decision_node": decision_node,
            "build_decision_node": build_decision_node,
            "normalize_state": normalize_state,
        }[name]
    raise AttributeError(name)
