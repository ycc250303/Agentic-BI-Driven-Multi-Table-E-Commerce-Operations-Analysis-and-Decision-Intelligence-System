from __future__ import annotations

from collections.abc import Callable

from .run import run_decision_state
from .state import BIState


def build_decision_node() -> Callable[[BIState], BIState]:
    """独立图节点工厂。协调器主图实际挂的是 orchestration/nodes.py::decision_node。"""

    def node(state: BIState) -> BIState:
        return run_decision_state(state)

    return node
