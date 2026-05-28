from __future__ import annotations

import json
from pathlib import Path

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


def test_what_if_remove_bad_sellers():
    state = load_case("high_seller_risk.json")
    result = run_what_if("remove_top_bad_sellers", {"top_n": 20}, state)
    assert result.scenario_type == "remove_top_bad_sellers"
    assert result.simulated_metrics["avg_review_score"] > result.baseline_metrics["avg_review_score"]
