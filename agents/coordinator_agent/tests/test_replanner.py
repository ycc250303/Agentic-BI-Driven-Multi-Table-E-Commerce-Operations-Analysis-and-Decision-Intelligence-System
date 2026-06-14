from __future__ import annotations

from agents.coordinator_agent.replanner import (
    ReplanDecision,
    apply_replan_decision,
    inspect_agent_outputs,
    plan_recovery_queries,
)
from agents.coordinator_agent.nodes import orchestrator_node
from agents.coordinator_agent.router import route_next_rule


class DummyStructuredResponse:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, messages):
        return self.payload


class DummyReplanModel:
    def __init__(self, payload):
        self.payload = payload

    def with_structured_output(self, schema):
        assert schema.__name__ == "ReplanDecision"
        return DummyStructuredResponse(self.payload)


class DummyMixedModel:
    def __init__(self):
        self.replan = ReplanDecision(
            should_replan=True,
            evidence_status="missing_inputs",
            sub_questions=["查询全市场与排除指定部分后的核心经营指标对比？"],
            suggested_agents=["data_analysis", "decision"],
            reason="缺少可由数据库补齐的经营基线。",
        )

    def with_structured_output(self, schema):
        assert schema.__name__ == "ReplanDecision"
        return DummyStructuredResponse(self.replan)

    def invoke(self, messages):
        raise AssertionError("orchestrator_node should use rule routing after replan in this test")


def test_missing_what_if_inputs_are_inspected_structurally():
    state = {
        "decision_result": {
            "what_if_result": {
                "status": "missing_inputs",
                "missing_inputs": ["market_baseline", "comparison_metrics"],
            }
        }
    }

    status, reason = inspect_agent_outputs(state)

    assert status == "missing_inputs"
    assert "What-if" in reason


def test_replan_missing_inputs_adds_data_analysis_and_resets_decision():
    state = {
        "user_query": "若不计入某部分市场，整体会怎么样？",
        "intent": "what_if",
        "sub_questions": [],
        "suggested_agents": ["decision"],
        "sql_runs": [],
        "agents_done": {"decision": True},
        "decision_result": {
            "what_if_result": {
                "status": "missing_inputs",
                "missing_inputs": ["market_baseline", "comparison_metrics"],
            }
        },
    }
    decision = plan_recovery_queries(
        state,
        model=DummyReplanModel(
            ReplanDecision(
                should_replan=True,
                evidence_status="missing_inputs",
                sub_questions=["查询全市场与排除指定部分后的核心经营指标对比？"],
                suggested_agents=["data_analysis", "decision"],
                reason="缺少可由数据库补齐的经营基线。",
            )
        ),
    )

    patch = apply_replan_decision(state, decision)

    assert patch["sub_questions"] == ["查询全市场与排除指定部分后的核心经营指标对比？"]
    assert patch["suggested_agents"] == ["data_analysis", "decision"]
    assert patch["replan_count"] == 1
    assert not patch["agents_done"].get("decision")


def test_router_does_not_synthesize_before_replan_budget_is_used():
    state = {
        "intent": "what_if",
        "sub_questions": ["查询补充基线？"],
        "suggested_agents": ["decision"],
        "sql_runs": [],
        "agents_done": {"decision": True},
        "decision_result": {
            "what_if_result": {
                "status": "missing_inputs",
                "missing_inputs": ["market_baseline"],
            }
        },
        "replan_count": 0,
        "replan_reason": "缺少可补充基线。",
    }

    decision = route_next_rule(state)

    assert decision.next_agent == "data_analysis"


def test_router_allows_synthesize_after_replan_budget_is_used():
    state = {
        "intent": "what_if",
        "sub_questions": [],
        "suggested_agents": ["decision"],
        "sql_runs": [],
        "agents_done": {"decision": True},
        "decision_result": {
            "what_if_result": {
                "status": "missing_inputs",
                "missing_inputs": ["external_elasticity"],
            }
        },
        "replan_count": 1,
    }

    decision = route_next_rule(state)

    assert decision.next_agent == "synthesize"


def test_empty_sql_result_is_treated_as_weak_evidence():
    state = {
        "sql_runs": [
            {
                "question": "q",
                "execute_sql_json": '{"ok": true, "results": [{"ok": true, "row_count_returned": 0}]}',
                "analysis_result": {"key_rows": [], "tables": [{"ok": True, "row_count": 0}]},
            }
        ]
    }

    status, reason = inspect_agent_outputs(state)

    assert status == "empty_or_weak"
    assert "数据分析" in reason


def test_orchestrator_replans_missing_inputs_before_synthesizing():
    state = {
        "user_query": "若不计入某部分市场，整体会怎么样？",
        "intent": "what_if",
        "sub_questions": [],
        "suggested_agents": ["decision"],
        "sql_runs": [],
        "agents_done": {"decision": True},
        "orchestrator_iterations": 1,
        "decision_result": {
            "what_if_result": {
                "status": "missing_inputs",
                "missing_inputs": ["market_baseline", "comparison_metrics"],
            }
        },
    }

    out = orchestrator_node(state, use_llm=False, model=DummyMixedModel())

    assert out["next_agent"] == "data_analysis"
    assert out["sub_questions"] == ["查询全市场与排除指定部分后的核心经营指标对比？"]
    assert out["replan_count"] == 1
