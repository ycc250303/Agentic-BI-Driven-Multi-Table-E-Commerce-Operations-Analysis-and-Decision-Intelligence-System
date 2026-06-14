from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from .schemas import DecisionResult, EvidenceBundle


class DecisionQualityReport(BaseModel):
    score: float = 1.0
    needs_revision: bool = False
    issues: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_evidence_notes: list[str] = Field(default_factory=list)
    recommendation_strength: str = "balanced"


_STRONG_CLAIMS = ("强烈建议", "一定", "必然", "积极进入", "显著提升")
_BOUNDARY_TERMS = (
    "直接证据",
    "间接",
    "代理",
    "无法直接",
    "不能直接",
    "证据不足",
    "缺少",
    "未提供",
    "基于当前证据",
)


def _contains_metric(text: str) -> bool:
    return bool(re.search(r"\d", text))


def _has_boundary_text(text: str) -> bool:
    return any(term in text for term in _BOUNDARY_TERMS)


def _has_proxy_evidence(bundle: EvidenceBundle) -> bool:
    for signal in bundle.signals:
        metadata = signal.metadata or {}
        if metadata.get("evidence_strength") == "proxy":
            return True
        if metadata.get("subject_match") == "partial":
            return True
    return False


def _what_if_ran(decision_result: DecisionResult) -> bool:
    return decision_result.what_if_result.status == "run"


def _what_if_has_simulated_values(decision_result: DecisionResult) -> bool:
    result = decision_result.what_if_result
    return bool(result.simulated_metrics or result.delta_metrics)


def evaluate_decision_quality(
    *,
    bundle: EvidenceBundle,
    decision_result: DecisionResult,
) -> DecisionQualityReport:
    answer = decision_result.narrative_answer or ""
    issues: list[str] = []
    unsupported_claims: list[str] = []
    missing_evidence_notes: list[str] = []
    recommendation_strength = "balanced"

    if not answer.strip():
        issues.append("narrative_answer 为空。")

    if not _contains_metric(answer) and not _has_boundary_text(answer):
        missing_evidence_notes.append(
            "回答未引用具体指标，也未说明本轮缺少直接指标。"
        )

    strong_terms = [term for term in _STRONG_CLAIMS if term in answer]
    if strong_terms:
        recommendation_strength = "strong"
        if _has_proxy_evidence(bundle) or not _has_boundary_text(answer):
            unsupported_claims.append(
                f"证据边界不足时使用了过强表述：{', '.join(strong_terms)}。"
            )

    if _has_proxy_evidence(bundle) and not _has_boundary_text(answer):
        missing_evidence_notes.append(
            "回答使用了代理或部分匹配证据，但没有说明证据边界。"
        )

    if not _what_if_ran(decision_result) and _what_if_has_simulated_values(decision_result):
        unsupported_claims.append(
            "What-if 结构化状态未标记为已运行，但包含模拟结果字段。"
        )

    all_issues = issues + unsupported_claims + missing_evidence_notes
    score = max(0.0, round(1.0 - 0.2 * len(all_issues), 2))
    return DecisionQualityReport(
        score=score,
        needs_revision=bool(all_issues),
        issues=all_issues,
        unsupported_claims=unsupported_claims,
        missing_evidence_notes=missing_evidence_notes,
        recommendation_strength=recommendation_strength,
    )


def quality_report_to_dict(report: DecisionQualityReport) -> dict[str, Any]:
    return report.model_dump(mode="json")
