from __future__ import annotations

from typing import Any, TypedDict


class BIState(TypedDict, total=False):
    """Compatibility-only state shape for orchestrators such as LangGraph.

    This is not the primary Decision-Agent input contract. New integrations
    should prefer `DecisionInputs` and the `answer_decision` / `run_decision`
    interfaces.
    """

    user_query: str
    intent: str
    task_plan: list[str]
    conversation_history: list[dict[str, str]]
    analysis_result: dict[str, Any]
    forecast_result: dict[str, Any]
    nlp_result: dict[str, Any]
    visualization_result: dict[str, Any]
    decision_result: dict[str, Any]
    final_answer: str
    warnings: list[str]
