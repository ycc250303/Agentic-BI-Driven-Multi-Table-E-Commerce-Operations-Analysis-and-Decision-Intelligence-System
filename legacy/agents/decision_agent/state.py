from __future__ import annotations

from typing import Any, TypedDict


class BIState(TypedDict, total=False):
    """协调器兼容态（LangGraph 共享 state 的子集）。

    主契约是 DecisionInputs / DecisionResult。本 TypedDict 只服务
    `run_decision_state`：读入上游证据，写出 decision_result / final_answer。
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
