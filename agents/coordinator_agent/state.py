from __future__ import annotations

from typing import Any, TypedDict


AgentName = str  # data_analysis | visualization | nlp | decision | synthesize


class AgentState(TypedDict, total=False):
    """LangGraph 全局共享状态。"""

    # --- 本轮问题 ---
    user_query: str  # 用户原话（多轮已解析为独立任务）；协调器新定义
    question: str  # 与 user_query 同步；NLP / 决策 Agent 同名字段

    # --- 分解 ---
    off_topic: bool  # 跑题则跳过子 Agent 直接拒答；协调器新定义
    intent: str  # 问题意图；协调器分解产出，决策 Agent 同名消费
    sub_questions: list[str]  # 拆出的单问题，查数按此逐条跑 SQL；协调器新定义
    suggested_agents: list[str]  # 本轮建议调度的 Agent；协调器新定义
    plan_reasoning: str  # 分解理由；协调器新定义
    task_plan: list[str]  # 步骤摘要；协调器分解产出，决策 Agent 同名消费

    # --- SQL Agent ---
    sql_pipeline: dict[str, Any]  # 单次查数流水线全量结果；SQL Agent
    rewrite_json: str  # 问题改写结果；SQL Agent
    generate_sql_json: str  # 生成的 SQL；SQL Agent
    execute_sql_json: str  # SQL 执行结果；SQL Agent
    sql_runs: list[dict[str, Any]]  # 多条单问题查数累积；协调器新定义
    analysis_result: dict[str, Any]  # 查数证据（供决策用）；协调器从 SQL Agent 结果收成

    # --- NLP Agent ---
    review_insights: dict[str, Any]  # 评论洞察（情感/主题/词云等）；NLP Agent
    nlp_result: dict[str, Any]  # 常镜像 review_insights；NLP Agent 产出，决策 Agent 消费

    # --- Visualization Agent ---
    visualization_result: dict[str, Any]  # 多图合并结果；可视化 Agent

    # --- Decision Agent ---
    decision_result: dict[str, Any]  # 行动建议、根因、质量报告等；决策 Agent
    what_if_result: dict[str, Any]  # What-if 仿真结果；决策 Agent

    # --- 编排控制 ---
    agents_done: dict[str, bool]  # 各 Agent 是否已跑完；协调器新定义
    execution_log: list[dict[str, Any]]  # 路由步骤日志；协调器新定义
    orchestrator_iterations: int  # 已路由次数；协调器新定义
    next_agent: AgentName  # 下一步要调度的 Agent；协调器新定义
    replan_count: int  # 补充规划次数；协调器新定义
    evidence_status: str  # 证据是否充足；协调器新定义
    replan_reason: str  # 补充规划原因；协调器新定义

    # --- 收尾 ---
    final_answer: str  # 面向业务的最终回答；协调器汇总产出，决策 Agent 同名
    warnings: list[str]  # 非致命问题；协调器新定义，决策 Agent 同名
    conversation_history: list[dict[str, str]]  # 多轮对话历史；协调器新定义，决策 Agent 同名
