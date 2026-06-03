"""协调器路由：suggested_agents 全链路强制执行测试。"""

from __future__ import annotations

from agents.coordinator_agent.router import choose_next_agent, route_next_rule


def _base_state(user_query: str) -> dict:
    return {
        "user_query": user_query,
        "intent": "diagnostic",
        "sub_questions": [user_query],
        "suggested_agents": ["data_analysis", "nlp", "visualization", "decision"],
        "sql_runs": [{"question": user_query, "execute_sql_json": '{"ok": true}'}],
        "agents_done": {"data_analysis": True},
        "orchestrator_iterations": 2,
    }


def test_negative_review_query_routes_nlp_before_viz():
    state = _base_state("Top 10 差评品类及其主要差评原因是什么？")
    d1 = route_next_rule(state)
    assert d1.next_agent == "nlp"

    state["agents_done"]["nlp"] = True
    state["review_insights"] = {
        "topic_distribution": {"price_freight": 40, "delivery_delay": 30},
        "complaints_by_category": [{"category": "bed_bath", "topic_distribution": {"price_freight": 5}}],
    }
    d2 = route_next_rule(state)
    assert d2.next_agent == "visualization"

    state["agents_done"]["visualization"] = True
    d3 = route_next_rule(state)
    assert d3.next_agent == "decision"

    state["agents_done"]["decision"] = True
    d4 = route_next_rule(state)
    assert d4.next_agent == "synthesize"


def test_llm_early_synthesize_overridden():
    state = _base_state("Top 10 差评品类及其主要差评原因是什么？")
    from agents.coordinator_agent.router import RouteDecision, _enforce_suggested_pipeline

    forced = _enforce_suggested_pipeline(
        RouteDecision(next_agent="synthesize", reasoning="证据已足够，剩余步骤不再必要"),
        state,
    )
    assert forced.next_agent == "nlp"
    assert "不得提前汇总" in forced.reasoning or "nlp" in forced.reasoning


def test_gmv_only_skips_post_agents_when_not_suggested():
    state = {
        "user_query": "2017年GMV是多少？",
        "intent": "descriptive",
        "sub_questions": ["2017年GMV是多少？"],
        "suggested_agents": ["data_analysis"],
        "sql_runs": [{"question": "q", "execute_sql_json": '{"ok": true}'}],
        "agents_done": {"data_analysis": True},
        "orchestrator_iterations": 2,
    }
    d = route_next_rule(state)
    assert d.next_agent == "synthesize"


def test_choose_next_agent_rule_mode():
    state = _base_state("Top 10 差评品类及其主要差评原因是什么？")
    d = choose_next_agent(state, use_llm=False)
    assert d.next_agent == "nlp"
