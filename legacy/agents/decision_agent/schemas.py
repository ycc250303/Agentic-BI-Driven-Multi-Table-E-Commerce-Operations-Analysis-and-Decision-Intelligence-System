"""决策 Agent 的输入 / 中间态 / 输出契约。

主路径：`DecisionInputs` → 规则层（证据包 / 打分 / 行动计划 / What-if）→ `DecisionResult`。
协调器共享 state 不是本文件的契约，需经 `adapters.decision_inputs_from_state` 转换后再进入流水线。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SeverityLevel = Literal["high", "medium", "low"]
DecisionTheme = Literal["物流优化", "卖家治理", "品类治理", "区域运营", "综合运营"]
DomainName = Literal["delivery", "seller", "category", "region", "forecast", "general"]
# What-if 执行态：缺 baseline/弹性时绝不伪造数值，只标 missing_inputs / directional_only
WhatIfStatus = Literal[
    "not_run",
    "run",
    "missing_inputs",
    "directional_only",
    "not_applicable",
]
WhatIfFormula = Literal[
    "add",
    "subtract",
    "multiply",
    "percent_change",
    "percentage_point_change",
]


class DecisionInputs(BaseModel):
    """核心入口契约。所有判断只能来自这些字段，禁止再查原始库。"""

    user_query: str
    # diagnostic / prescriptive / predictive / what_if；影响告警与是否规划模拟
    intent: str = "prescriptive"
    # SQL 查数标准化结果：summary_text / kpis / findings / tables / simulation_inputs
    analysis_result: dict[str, Any]
    # 评论洞察：negative_topics / worst_categories / worst_states / sentiment_overview
    nlp_result: dict[str, Any] = Field(default_factory=dict)
    # 预测：trend_direction / risk_flags / forecast_values；可为空
    forecast_result: dict[str, Any] = Field(default_factory=dict)
    # 图表摘要；决策只读 summary_text，不出图
    visualization_result: dict[str, Any] = Field(default_factory=dict)
    # 上游已跑过的模拟；新路径优先走 plan_what_if + run_what_if
    what_if_result: dict[str, Any] = Field(default_factory=dict)
    conversation_history: list[dict[str, str]] = Field(default_factory=list)


class DecisionSignal(BaseModel):
    """单条阈值信号。由证据包从 KPI / findings / NLP / 预测抽出，供规则打分消费。"""

    domain: DomainName
    signal: str
    value: float | str | None = None
    benchmark: float | str | None = None
    severity_score: float = Field(ge=0.0, le=1.0)
    evidence_text: str
    # evidence_strength=direct|proxy；subject_match=exact|partial|unknown
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceBundle(BaseModel):
    """规则层统一证据包：把多源上游结果压成可打分的 signals。"""

    query_goal: str
    business_scope: str
    signals: list[DecisionSignal] = Field(default_factory=list)
    source_summaries: dict[str, str] = Field(default_factory=dict)


class ScoredProblem(BaseModel):
    """按域聚合后的优先问题。priority = 0.5*impact + 0.3*urgency + 0.2*feasibility。"""

    problem_type: DomainName
    decision_theme: DecisionTheme
    problem: str
    evidence: list[str]
    severity: SeverityLevel
    impact_score: float = Field(ge=0.0, le=1.0)
    urgency_score: float = Field(ge=0.0, le=1.0)
    feasibility_score: float = Field(ge=0.0, le=1.0)
    priority_score: float = Field(ge=0.0, le=1.0)
    root_cause_candidates: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionPlanItem(BaseModel):
    """规则模板生成的可执行动作。priority 为 P1/P2/P3，对应打分后的 Top3 问题。"""

    priority: str
    action: str
    owner: str
    reason: str
    target_kpi: str
    target_value: str
    time_horizon: str
    expected_impact: str


class RootCauseItem(BaseModel):
    cause: str
    supporting_evidence: list[str]


class WhatIfIntervention(BaseModel):
    domain: str = "general"
    target: str = ""
    action: str = ""
    assumption_text: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class WhatIfComputation(BaseModel):
    target_metric: str
    baseline_value: float | None = None
    change_value: float | None = None
    formula: WhatIfFormula = "add"
    baseline_source: str = ""
    change_source: str = ""
    unit: str = ""


class WhatIfPlan(BaseModel):
    """LLM 结构化规划：只声明干预、公式和缺口，不在此步算数值。"""

    has_what_if_intent: bool = False
    plan_type: str = "generic_what_if"
    question: str = ""
    interventions: list[WhatIfIntervention] = Field(default_factory=list)
    target_metrics: list[str] = Field(default_factory=list)
    computations: list[WhatIfComputation] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    can_quantify: bool = False
    directional_only: bool = False
    reasoning_summary: str = ""
    limitations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class WhatIfResult(BaseModel):
    """确定性执行器输出。缺数时 status≠run，禁止用 0 / 经验弹性填洞。"""

    scenario_type: str = ""
    status: WhatIfStatus = "not_run"
    parameters: dict[str, Any] = Field(default_factory=dict)
    baseline_metrics: dict[str, Any] = Field(default_factory=dict)
    simulated_metrics: dict[str, Any] = Field(default_factory=dict)
    delta_metrics: dict[str, Any] = Field(default_factory=dict)
    summary_text: str = ""
    limitations: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)


class DecisionResult(BaseModel):
    """对外主输出。协调器写入 state.decision_result，final_answer 取 narrative_answer。"""

    decision_theme: DecisionTheme = "综合运营"
    problem_statement: str = ""
    key_findings: list[dict[str, Any]] = Field(default_factory=list)
    root_causes: list[RootCauseItem] = Field(default_factory=list)
    action_plan: list[ActionPlanItem] = Field(default_factory=list)
    what_if_result: WhatIfResult = Field(default_factory=WhatIfResult)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    narrative_answer: str = ""
    quality_report: dict[str, Any] = Field(default_factory=dict)
    revision_count: int = 0
