from __future__ import annotations

from agents.decision_agent.quality import evaluate_decision_quality
from agents.decision_agent.schemas import DecisionResult, DecisionSignal, EvidenceBundle


def test_quality_checker_flags_overstrong_proxy_claims():
    bundle = EvidenceBundle(
        query_goal="是否适合入行某品类？",
        business_scope="prescriptive",
        signals=[
            DecisionSignal(
                domain="category",
                signal="negative quality rate",
                severity_score=0.7,
                evidence_text="相邻品类负面率偏高。",
                metadata={
                    "evidence_strength": "proxy",
                    "subject_match": "partial",
                },
            )
        ],
    )
    decision_result = DecisionResult(
        narrative_answer="强烈建议积极进入该品类，预计提升收益。",
    )
    report = evaluate_decision_quality(
        bundle=bundle,
        decision_result=decision_result,
    )
    assert report.needs_revision
    assert report.recommendation_strength == "strong"
    assert report.unsupported_claims
