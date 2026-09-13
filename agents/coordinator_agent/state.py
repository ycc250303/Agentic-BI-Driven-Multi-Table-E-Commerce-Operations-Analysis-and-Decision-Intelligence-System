from __future__ import annotations

from typing import Any, TypedDict


# 取值见 agents/coordinator_agent/orchestration/router.py::AgentRoute
AgentName = str  # data_analysis | visualization | nlp | decision | synthesize


class AgentState(TypedDict, total=False):
    """LangGraph 全局共享状态。子 Agent 写入的结构在字段注释里指向定义文件。"""

    # --- 本轮问题 ---
    user_query: str  # 用户原话；多轮时已是会话解析后的独立任务
    question: str  # 与 user_query 同步；NLP/决策读取同名字段（nlp_agent/state.py、decision_agent/state.py）

    # --- 分解（本 Agent：orchestration/decomposer.py::DecomposeResult）---
    off_topic: bool  # True 则跳过子 Agent，直接 synthesize 拒答
    intent: str  # planner.py::IntentName；决策侧 DecisionInputs.intent 同名
    sub_questions: list[str]  # 拆出的单问题；查数按此逐条跑 SQL
    suggested_agents: list[str]  # 本轮建议调度的 AgentName；路由会强制跑完
    plan_reasoning: str  # 分解理由（LLM 或规则回退）
    task_plan: list[str]  # 步骤摘要；决策 BIState.task_plan 同名

    # --- SQL Agent 查数 ---
    # 单次流水线全量 dict：agents/sql_agent/pipeline.py::run_sql_pipeline_with_feedback 返回值
    #   内含 rewrite_json / generate_sql_json / check_sql_json / execute_sql_json 及 attempts
    sql_pipeline: dict[str, Any]
    # RewriteToQueryOutput JSON（含 SubQuestion、QueryScope）
    # → agents/sql_agent/tools/rewrite_to_query.py
    rewrite_json: str
    # GenerateSqlOutput JSON
    # → agents/sql_agent/tools/generate_sql.py
    generate_sql_json: str
    # ExecuteSqlOutput JSON（results[] 为 ExecuteSqlResultItem）
    # → agents/sql_agent/tools/execute_sql.py
    execute_sql_json: str
    # 多次单问题累积。元素：question / index / sql_pipeline / analysis_result / execute_sql_json
    # sql_pipeline、execute_sql_json 形状同上（SQL Agent）；analysis_result 见下一字段
    sql_runs: list[dict[str, Any]]
    # 协调器把 SQL 结果收成决策可用的查数证据
    # 写入：orchestration/adapters.py::build_analysis_result_from_sql_pipeline / merge_sql_runs
    # 消费：decision_agent/adapters.py::normalize_analysis_result、schemas.py::DecisionInputs.analysis_result
    analysis_result: dict[str, Any]

    # --- NLP Agent ---
    # 评论洞察主契约 ReviewInsightsPayload
    # → agents/nlp_agent/state.py
    # 嵌套来源：
    #   关键词主题 ReviewInsightOutput → nlp_agent/tools/topic_keyword.py
    #   sentiment → nlp_agent/tools/sentiment.py::aggregate_sentiment
    #   wordcloud → nlp_agent/tools/wordcloud_data.py
    #   topics_bertopic → nlp_agent/tools/topic_model.py::aggregate_bertopic
    review_insights: dict[str, Any]
    # 常镜像 review_insights；决策消费前会标准化
    # → decision_agent/adapters.py::normalize_nlp_result、DecisionInputs.nlp_result
    nlp_result: dict[str, Any]

    # --- Visualization Agent ---
    # 多图合并结果 {summary_text, charts[], chart_type_counts}
    # → viz_agent/data/sql_result.py::merge_visualization_results
    # charts[] 单项来自 VisualizationAgentOutput（plan 为 VizPlan）
    # → viz_agent/schema.py
    # 套件规划（出哪些图）VizSuitePlan / VizChartTask → viz_agent/plan/tasks.py
    visualization_result: dict[str, Any]

    # --- Decision Agent ---
    # DecisionResult（含 action_plan、root_causes、quality_report 等）
    # → decision_agent/schemas.py::DecisionResult
    decision_result: dict[str, Any]
    # WhatIfResult；也可能嵌在 decision_result["what_if_result"]
    # → decision_agent/schemas.py::WhatIfResult（status 见同文件 WhatIfStatus）
    what_if_result: dict[str, Any]

    # --- 编排控制（本 Agent）---
    agents_done: dict[str, bool]  # AgentName → 是否已跑完
    execution_log: list[dict[str, Any]]  # {step, next_agent, reasoning}；nodes.py 写入
    orchestrator_iterations: int  # 路由次数；上限 router.py::MAX_ORCHESTRATOR_ITERATIONS
    next_agent: AgentName  # router.py::RouteDecision.next_agent
    replan_count: int  # 补充规划次数；上限 replanner.py::MAX_REPLAN_COUNT
    evidence_status: str  # sufficient | empty_or_weak | missing_inputs；replanner.py::inspect_agent_outputs
    replan_reason: str  # replanner.py::ReplanDecision.reason

    # --- 收尾 ---
    final_answer: str  # synthesize 面向业务的最终回答；决策 BIState.final_answer 同名
    warnings: list[str]  # 非致命问题；决策 BIState.warnings 同名
    # {role, content}；本 Agent：session/memory.py::build_conversation_history
    # 决策：schemas.py::DecisionInputs.conversation_history
    conversation_history: list[dict[str, str]]
