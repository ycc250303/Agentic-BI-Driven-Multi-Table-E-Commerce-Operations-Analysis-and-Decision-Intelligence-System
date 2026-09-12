"""Public exports for Decision-Agent.

Preferred entrypoints:
- `answer_decision`
- `run_decision`
- `run_decision_state`
"""

__all__ = [
    "DecisionInputs",
    "DecisionResult",
    "answer_decision",
    "run_decision",
    "run_decision_state",
    "normalize_state",
]


def __getattr__(name: str):
    if name in __all__:
        from .adapters import normalize_state
        from .schemas import DecisionInputs, DecisionResult
        from .run import run_decision_state
        from .service import answer_decision, run_decision

        return {
            "DecisionInputs": DecisionInputs,
            "DecisionResult": DecisionResult,
            "answer_decision": answer_decision,
            "run_decision": run_decision,
            "run_decision_state": run_decision_state,
            "normalize_state": normalize_state,
        }[name]
    raise AttributeError(name)
