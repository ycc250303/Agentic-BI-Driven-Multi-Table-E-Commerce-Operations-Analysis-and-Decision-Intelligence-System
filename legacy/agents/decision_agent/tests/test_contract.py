from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.decision_agent.run import run_decision_state


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_case(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _stub_llm(stub_decision_llm):
    stub_decision_llm(
        narrative={
            "narrative_answer": "这是联调节点测试输出。",
            "risks": ["节点测试未接入真实 API"],
            "assumptions": ["状态已通过兼容层转换为核心输入"],
        }
    )


def test_run_decision_state_preserves_state_contract():
    state = load_case("high_delivery_risk.json")
    out = run_decision_state(state)
    assert isinstance(out, dict)
    assert "decision_result" in out
    assert "final_answer" in out
    assert out["decision_result"]["decision_theme"] == "物流优化"
    assert out["decision_result"]["action_plan"]
    assert out["decision_result"]["what_if_result"]["status"] == "not_run"
    assert out["final_answer"] == "这是联调节点测试输出。"
    assert "warnings" in out


def test_run_decision_state_consumes_agent_tpc_upstream_state():
    state = load_case("upstream_state_from_agent_tpc.json")
    out = run_decision_state(state)
    assert out["decision_result"]["action_plan"]
    assert out["decision_result"]["what_if_result"]["scenario_type"] == "remove_top_bad_sellers"
    assert out["decision_result"]["what_if_result"]["status"] == "run"
    assert any(
        finding["problem"]
        for finding in out["decision_result"]["key_findings"]
        if finding["severity"] in {"medium", "high"}
    )


def test_run_decision_state_consumes_sql_only_delivery_state():
    state = load_case("upstream_state_sql_agent_delivery_only.json")
    out = run_decision_state(state)
    assert out["decision_result"]["decision_theme"] == "物流优化"
    assert out["decision_result"]["action_plan"]


def test_run_decision_state_consumes_sql_only_seller_state():
    state = load_case("upstream_state_sql_agent_seller_only.json")
    out = run_decision_state(state)
    assert out["decision_result"]["decision_theme"] == "卖家治理"
    assert out["decision_result"]["what_if_result"]["status"] == "not_run"


def test_run_decision_state_consumes_sql_only_category_state():
    state = load_case("upstream_state_sql_agent_category_only.json")
    out = run_decision_state(state)
    assert out["decision_result"]["decision_theme"] == "品类治理"
