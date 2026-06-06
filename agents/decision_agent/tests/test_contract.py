from __future__ import annotations

import json
from pathlib import Path

from agents.decision_agent.langgraph_node import build_decision_node


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_case(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class DummyStructuredResponse:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, messages):
        return self.payload


class DummyModel:
    def with_structured_output(self, schema):
        return DummyStructuredResponse(
            {
                "narrative_answer": "这是联调节点测试输出。",
                "risks": ["节点测试未接入真实 API"],
                "assumptions": ["状态已通过兼容层转换为核心输入"],
            }
        )


def test_langgraph_node_preserves_state_contract():
    state = load_case("high_delivery_risk.json")
    node = build_decision_node(model=DummyModel())
    out = node(state)
    assert isinstance(out, dict)
    assert "decision_result" in out
    assert "final_answer" in out
    assert out["decision_result"]["decision_theme"] == "物流优化"
    assert out["final_answer"] == "这是联调节点测试输出。"


def test_langgraph_node_consumes_agent_tpc_upstream_state():
    state = load_case("upstream_state_from_agent_tpc.json")
    node = build_decision_node(model=DummyModel())
    out = node(state)
    assert out["decision_result"]["action_plan"]
    assert out["decision_result"]["what_if_result"]["scenario_type"] == "remove_top_bad_sellers"
    assert out["decision_result"]["what_if_result"]["status"] == "run"
    assert any(
        finding["problem"]
        for finding in out["decision_result"]["key_findings"]
        if finding["severity"] in {"medium", "high"}
    )


def test_langgraph_node_consumes_sql_only_delivery_state():
    state = load_case("upstream_state_sql_agent_delivery_only.json")
    node = build_decision_node(model=DummyModel())
    out = node(state)
    assert out["decision_result"]["decision_theme"] == "物流优化"
    assert out["decision_result"]["action_plan"]


def test_langgraph_node_consumes_sql_only_seller_state():
    state = load_case("upstream_state_sql_agent_seller_only.json")
    node = build_decision_node(model=DummyModel())
    out = node(state)
    assert out["decision_result"]["decision_theme"] == "卖家治理"
    assert out["decision_result"]["what_if_result"]["scenario_type"] == "remove_top_bad_sellers"


def test_langgraph_node_consumes_sql_only_category_state():
    state = load_case("upstream_state_sql_agent_category_only.json")
    node = build_decision_node(model=DummyModel())
    out = node(state)
    assert out["decision_result"]["decision_theme"] == "品类治理"
