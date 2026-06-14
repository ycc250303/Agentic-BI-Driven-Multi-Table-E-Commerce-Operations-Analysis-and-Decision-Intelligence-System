from __future__ import annotations

from agents.decision_agent.quality import evaluate_decision_quality
from agents.decision_agent.schemas import DecisionResult, DecisionSignal, EvidenceBundle, WhatIfResult


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


def test_quality_checker_does_not_treat_action_targets_as_what_if_numbers():
    bundle = EvidenceBundle(
        query_goal="给出运营行动目标",
        business_scope="prescriptive",
    )
    examples = [
        "建议将重点区域负面率作为行动目标，目标下降到 22% 以下。",
        "建议对问题品类治理，目标为 1 个周期内下降 5 个百分点。",
        "行动 KPI 是预计下降 5 个百分点，这是治理目标而非模拟结果。",
    ]

    for text in examples:
        report = evaluate_decision_quality(
            bundle=bundle,
            decision_result=DecisionResult(narrative_answer=text),
        )

        assert "What-if 未实际运行时，回答中出现了模拟式数值结论。" not in report.issues
        assert not report.unsupported_claims


def test_quality_checker_flags_inconsistent_what_if_structured_state():
    bundle = EvidenceBundle(
        query_goal="评估模拟结果",
        business_scope="what_if",
    )
    decision_result = DecisionResult(
        narrative_answer="当前已有模拟结果。",
        what_if_result=WhatIfResult(
            status="not_run",
            simulated_metrics={"gmv": 1_100_000},
        ),
    )

    report = evaluate_decision_quality(
        bundle=bundle,
        decision_result=decision_result,
    )

    assert report.needs_revision
    assert any("结构化状态" in issue for issue in report.issues)
