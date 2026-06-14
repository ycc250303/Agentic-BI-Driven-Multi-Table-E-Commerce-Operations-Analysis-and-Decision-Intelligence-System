from __future__ import annotations

import json
from pathlib import Path

from agents.decision_agent.schemas import WhatIfComputation, WhatIfPlan
from agents.decision_agent.tools.build_evidence_bundle import build_evidence_bundle
from agents.decision_agent.tools.score_problems import score_problems
from agents.decision_agent.tools.run_what_if import run_what_if


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_case(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_delivery_rule_triggers():
    state = load_case("high_delivery_risk.json")
    bundle = build_evidence_bundle(state)
    problems = score_problems(bundle)
    assert problems[0].problem_type == "delivery"
    assert problems[0].decision_theme == "物流优化"
    assert problems[0].priority_score > 0.5


def test_seller_rule_triggers():
    state = load_case("high_seller_risk.json")
    bundle = build_evidence_bundle(state)
    problems = score_problems(bundle)
    assert any(p.problem_type == "seller" for p in problems)
    seller_problem = next(p for p in problems if p.problem_type == "seller")
    assert seller_problem.decision_theme == "卖家治理"
    assert seller_problem.priority_score > 0.5


def test_category_rule_triggers():
    state = load_case("category_risk.json")
    bundle = build_evidence_bundle(state)
    problems = score_problems(bundle)
    assert any(p.problem_type == "category" for p in problems)
    category_problem = next(p for p in problems if p.problem_type == "category")
    assert category_problem.decision_theme == "品类治理"


def test_what_if_generic_quantified_percent_change():
    plan = WhatIfPlan(
        has_what_if_intent=True,
        question="如果 GMV 基线 100 万、转化提升 10%，GMV 会怎样？",
        can_quantify=True,
        computations=[
            WhatIfComputation(
                target_metric="gmv",
                baseline_value=1_000_000,
                change_value=0.10,
                formula="percent_change",
                baseline_source="用户假设",
                change_source="用户假设",
            )
        ],
    )

    result = run_what_if(plan, {})

    assert result.scenario_type == "quantified_what_if"
    assert result.status == "run"
    assert result.simulated_metrics["gmv"] == 1_100_000
    assert result.delta_metrics["gmv"] > 0


def test_what_if_missing_inputs_does_not_fake_simulation():
    plan = WhatIfPlan(
        has_what_if_intent=True,
        question="如果差评率降低 5 个百分点，销售额会怎样？",
        can_quantify=False,
        missing_inputs=["negative_rate_to_gmv_elasticity"],
    )

    result = run_what_if(plan, {})

    assert result.status == "missing_inputs"
    assert result.baseline_metrics == {}
    assert result.simulated_metrics == {}
    assert result.missing_inputs


def test_what_if_directional_only_does_not_fake_numbers():
    plan = WhatIfPlan(
        has_what_if_intent=True,
        question="如果加大 SP 州运营投入会怎样？",
        can_quantify=False,
        directional_only=True,
        missing_inputs=["investment_amount", "expected_conversion_lift"],
        reasoning_summary="当前只能判断投入可能影响转化与履约压力，但缺少投入产出参数。",
    )

    result = run_what_if(plan, {})

    assert result.status == "directional_only"
    assert result.baseline_metrics == {}
    assert result.simulated_metrics == {}
