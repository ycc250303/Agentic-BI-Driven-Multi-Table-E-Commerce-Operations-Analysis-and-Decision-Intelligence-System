from __future__ import annotations

import json
from pathlib import Path

from agents.decision_agent.run import DecisionAgent, run_decision_state


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_case(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class DummyStructuredResponse:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, messages):
        return self.payload


class DummyModel:
    def __init__(self):
        self.first = True

    def with_structured_output(self, schema):
        if schema.__name__ == "WhatIfPlan":
            return DummyStructuredResponse(
                {
                    "has_what_if_intent": False,
                    "question": "",
                }
            )
        if self.first:
            self.first = False
            return DummyStructuredResponse(
                {
                    "narrative_answer": "根据证据，优先治理配送延迟与高负面区域。",
                    "risks": ["测试模式下未接入真实 API"],
                    "assumptions": ["使用 fixture 数据进行验证"],
                }
            )
        return DummyStructuredResponse(
            {
                "narrative_answer": "根据证据，建议先治理核心问题并跟踪 What-if。",
                "risks": ["测试模式下未接入真实 API"],
                "assumptions": ["使用 fixture 数据进行验证"],
            }
        )


def test_decision_agent_smoke():
    agent = DecisionAgent(model=DummyModel())
    state = load_case("high_delivery_risk.json")
    result = agent.run(state)
    assert "decision_result" in result
    assert result["final_answer"]
    assert "warnings" in result
    assert result["decision_result"]["action_plan"]
    assert result["decision_result"]["what_if_result"]["status"] == "not_run"


def test_run_decision_state_smoke():
    state = load_case("high_delivery_risk.json")
    result = run_decision_state(state, model=DummyModel())
    assert "decision_result" in result
    assert result["final_answer"]
    assert "warnings" in result
