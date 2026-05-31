from __future__ import annotations

from typing import Any, TypedDict


AgentName = str  # data_analysis | visualization | nlp | decision | synthesize


class AgentState(TypedDict, total=False):
    """LangGraph 全局共享状态。"""

    user_query: str
    question: str

    intent: str
    sub_questions: list[str]
    suggested_agents: list[str]
    plan_reasoning: str
    task_plan: list[str]

    sql_runs: list[dict[str, Any]]
    analysis_result: dict[str, Any]

    rewrite_json: str
    execute_sql_json: str
    generate_sql_json: str
    sql_pipeline: dict[str, Any]

    nlp_result: dict[str, Any]
    review_insights: dict[str, Any]
    visualization_result: dict[str, Any]
    what_if_result: dict[str, Any]
    decision_result: dict[str, Any]

    agents_done: dict[str, bool]
    execution_log: list[dict[str, Any]]
    orchestrator_iterations: int
    next_agent: AgentName

    final_answer: str
    warnings: list[str]
    conversation_history: list[dict[str, str]]
