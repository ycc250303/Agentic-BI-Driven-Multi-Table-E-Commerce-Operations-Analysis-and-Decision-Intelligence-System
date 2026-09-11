from __future__ import annotations

from agents.coordinator_agent.orchestration.decomposer import (
    LLM_STRUCTURED_FALLBACK,
    DecomposeResult,
    decompose_query_llm,
)
from agents.coordinator_agent.orchestration.nodes import decompose_node, orchestrator_node
from agents.coordinator_agent.orchestration.router import RouteDecision, route_next_llm


class _StructuredModel:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, messages):
        if self.error is not None:
            raise self.error
        return self.payload


def test_decompose_query_llm_uses_structured_output():
    payload = DecomposeResult(
        intent="descriptive",
        sub_questions=["2017年哪个州的销售额最高？"],
        suggested_agents=["data_analysis"],
        reasoning="单问题描述性查询",
    )
    result = decompose_query_llm(
        "2017年哪个州的销售额最高？",
        model=_StructuredModel(payload),
    )
    assert result.sub_questions == ["2017年哪个州的销售额最高？"]
    assert LLM_STRUCTURED_FALLBACK not in result.reasoning


def test_decompose_query_llm_falls_back_on_schema_failure():
    result = decompose_query_llm(
        "2017年哪个州的销售额最高？",
        model=_StructuredModel(error=ValueError("bad schema")),
    )
    assert result.sub_questions
    assert LLM_STRUCTURED_FALLBACK in result.reasoning


def test_decompose_node_warns_on_llm_fallback():
    out = decompose_node(
        {"user_query": "2017年哪个州的销售额最高？"},
        model=_StructuredModel(error=ValueError("bad schema")),
    )
    assert any(LLM_STRUCTURED_FALLBACK in w for w in (out.get("warnings") or []))
    assert out.get("sub_questions")


def test_route_next_llm_uses_structured_output():
    state = {
        "user_query": "2017年GMV是多少？",
        "intent": "descriptive",
        "sub_questions": ["2017年GMV是多少？"],
        "suggested_agents": ["data_analysis"],
        "sql_runs": [
            {
                "question": "2017年GMV是多少？",
                "execute_sql_json": '{"ok": true, "results": [{"ok": true, "row_count_returned": 1}]}',
                "analysis_result": {"key_rows": [{"gmv": 1}]},
            }
        ],
        "agents_done": {"data_analysis": True},
        "orchestrator_iterations": 2,
    }
    decision = route_next_llm(
        state,
        model=_StructuredModel(RouteDecision(next_agent="synthesize", reasoning="查数已完成")),
    )
    assert decision.next_agent == "synthesize"
    assert LLM_STRUCTURED_FALLBACK not in decision.reasoning


def test_orchestrator_warns_on_route_llm_fallback():
    state = {
        "user_query": "2017年GMV是多少？",
        "intent": "descriptive",
        "sub_questions": ["2017年GMV是多少？"],
        "suggested_agents": ["data_analysis"],
        "sql_runs": [
            {
                "question": "2017年GMV是多少？",
                "execute_sql_json": '{"ok": true, "results": [{"ok": true, "row_count_returned": 1}]}',
                "analysis_result": {"key_rows": [{"gmv": 1}]},
            }
        ],
        "agents_done": {"data_analysis": True},
        "orchestrator_iterations": 1,
    }
    out = orchestrator_node(
        state,
        use_llm=True,
        model=_StructuredModel(error=ValueError("bad schema")),
    )
    assert out["next_agent"] == "synthesize"
    assert any(LLM_STRUCTURED_FALLBACK in w for w in (out.get("warnings") or []))
