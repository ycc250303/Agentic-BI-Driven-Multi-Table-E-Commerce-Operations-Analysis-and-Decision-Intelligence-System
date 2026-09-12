from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.decision_agent.run import DecisionAgent, run_decision_state


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_case(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _stub_llm(stub_decision_llm):
    stub_decision_llm()


def test_decision_agent_smoke():
    agent = DecisionAgent()
    state = load_case("high_delivery_risk.json")
    result = agent.run(state)
    assert "decision_result" in result
    assert result["final_answer"]
    assert "warnings" in result
    assert result["decision_result"]["action_plan"]
    assert result["decision_result"]["what_if_result"]["status"] == "not_run"


def test_run_decision_state_smoke():
    state = load_case("high_delivery_risk.json")
    result = run_decision_state(state)
    assert "decision_result" in result
    assert result["final_answer"]
    assert "warnings" in result
