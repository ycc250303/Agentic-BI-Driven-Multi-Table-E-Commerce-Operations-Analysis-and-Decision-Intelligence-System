from __future__ import annotations

from collections.abc import Callable

from .adapters import normalize_state
from .run import DecisionAgent
from .state import BIState


def build_decision_node(model=None) -> Callable[[BIState], BIState]:
    agent = DecisionAgent(model=model)

    def node(state: BIState) -> BIState:
        normalized_state = normalize_state(state)
        return agent.run(normalized_state)

    return node
