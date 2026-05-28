__all__ = ["DecisionAgent", "decision_node", "build_decision_node", "normalize_state"]


def __getattr__(name: str):
    if name in __all__:
        from .adapters import normalize_state
        from .langgraph_node import build_decision_node
        from .run import DecisionAgent, decision_node

        return {
            "DecisionAgent": DecisionAgent,
            "decision_node": decision_node,
            "build_decision_node": build_decision_node,
            "normalize_state": normalize_state,
        }[name]
    raise AttributeError(name)
