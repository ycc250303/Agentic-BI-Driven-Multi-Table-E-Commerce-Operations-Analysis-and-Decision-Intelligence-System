from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SeverityLevel = Literal["high", "medium", "low"]
DecisionTheme = Literal["物流优化", "卖家治理", "品类治理", "区域运营", "综合运营"]
DomainName = Literal["delivery", "seller", "category", "region", "forecast", "general"]


class DecisionInputs(BaseModel):
    user_query: str
    intent: str = "prescriptive"
    analysis_result: dict[str, Any]
    nlp_result: dict[str, Any] = Field(default_factory=dict)
    forecast_result: dict[str, Any] = Field(default_factory=dict)
    visualization_result: dict[str, Any] = Field(default_factory=dict)
    what_if_result: dict[str, Any] = Field(default_factory=dict)
    conversation_history: list[dict[str, str]] = Field(default_factory=list)


class DecisionSignal(BaseModel):
    domain: DomainName
    signal: str
    value: float | str | None = None
    benchmark: float | str | None = None
    severity_score: float = Field(ge=0.0, le=1.0)
    evidence_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceBundle(BaseModel):
    query_goal: str
    business_scope: str
    signals: list[DecisionSignal] = Field(default_factory=list)
    source_summaries: dict[str, str] = Field(default_factory=dict)


class ScoredProblem(BaseModel):
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


class WhatIfResult(BaseModel):
    scenario_type: str = ""
    status: str = "not_run"
    parameters: dict[str, Any] = Field(default_factory=dict)
    baseline_metrics: dict[str, Any] = Field(default_factory=dict)
    simulated_metrics: dict[str, Any] = Field(default_factory=dict)
    delta_metrics: dict[str, Any] = Field(default_factory=dict)
    summary_text: str = ""
    limitations: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)


class DecisionResult(BaseModel):
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
