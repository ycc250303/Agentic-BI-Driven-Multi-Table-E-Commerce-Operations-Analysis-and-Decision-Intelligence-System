from __future__ import annotations

from collections.abc import Callable

from .run import run_decision_state
from .state import BIState


def build_decision_node(model=None) -> Callable[[BIState], BIState]:
    def node(state: BIState) -> BIState:
        return run_decision_state(state, model=model)

    return node
