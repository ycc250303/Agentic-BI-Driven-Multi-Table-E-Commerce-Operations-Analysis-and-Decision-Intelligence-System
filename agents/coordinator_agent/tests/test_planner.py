from __future__ import annotations

from agents.coordinator_agent.decomposer import (
    DecomposeResult,
    decompose_query_llm,
    decompose_query_rule,
    finalize_suggested_agents,
)
from agents.coordinator_agent.planner import classify_intent
from agents.coordinator_agent.router import route_next_rule


def test_classify_prescriptive():
    q = "基于全部分析结果，给出平台 3 个月内的三大优先改进策略。"
    assert classify_intent(q) == "prescriptive"


def test_classify_descriptive():
    q = "2017 年 GMV 是多少？按月和各州排名的趋势怎样？"
    assert classify_intent(q) == "descriptive"


def test_decompose_splits_compound_question():
    result = decompose_query_rule(
        "2017年哪个州的销售额最高？交付准时率是多少？哪种支付方式最受欢迎？"
    )
    assert len(result.sub_questions) == 3


def test_decompose_single_question():
    result = decompose_query_rule("2017年哪个州的销售额最高？")
    assert len(result.sub_questions) == 1


class DummyMessage:
    def __init__(self, content: str):
        self.content = content


class DummyDecomposeModel:
    def __init__(self, payload: str):
        self.payload = payload

    def invoke(self, messages):
        return DummyMessage(self.payload)


def test_rule_decompose_does_not_classify_what_if_by_keywords():
    result = decompose_query_rule("如果 GMV 基线 100 万、转化提升 10%，GMV 会怎样？")
    assert result.intent != "what_if"
    assert result.sub_questions


def test_rule_decompose_action_target_is_not_what_if():
    result = decompose_query_rule("建议重点区域负面率下降到 22% 以下")
    assert result.intent != "what_if"
    assert result.sub_questions


def test_llm_decompose_self_contained_what_if_routes_directly_to_decision():
    result = decompose_query_llm(
        "如果 GMV 基线 100 万、转化提升 10%，GMV 会怎样？",
        model=DummyDecomposeModel(
            """
            {
              "intent": "what_if",
              "sub_questions": [],
              "suggested_agents": ["decision"],
              "reasoning": "LLM 判断为自带假设的 What-if。",
              "off_topic": false
            }
            """
        ),
    )
    assert result.intent == "what_if"
    assert result.sub_questions == []
    assert result.suggested_agents == ["decision"]


def test_llm_decompose_data_dependent_what_if_keeps_analysis_route():
    result = decompose_query_llm(
        "如果下架当前差评率最高的卖家会怎样？",
        model=DummyDecomposeModel(
            """
            {
              "intent": "what_if",
              "sub_questions": ["查询当前差评率最高的卖家及其基线指标？"],
              "suggested_agents": ["data_analysis", "decision"],
              "reasoning": "LLM 判断需要先查当前基线。",
              "off_topic": false
            }
            """
        ),
    )
    assert result.intent == "what_if"
    assert result.sub_questions == ["查询当前差评率最高的卖家及其基线指标？"]
    assert result.suggested_agents == ["data_analysis", "decision"]


def test_finalize_preserves_llm_data_dependent_what_if_route():
    result = DecomposeResult(
        intent="what_if",
        sub_questions=["查询当前差评率最高的卖家及其基线指标？"],
        suggested_agents=["data_analysis", "decision"],
        reasoning="llm",
    )
    out = finalize_suggested_agents(result, "如果下架当前差评率最高的卖家会怎样？")
    assert out.sub_questions == ["查询当前差评率最高的卖家及其基线指标？"]
    assert "data_analysis" in out.suggested_agents
    assert "decision" in out.suggested_agents


def test_decompose_splits_jiqi_query():
    result = decompose_query_rule("Top 10 差评品类及其主要差评原因是什么？")
    assert len(result.sub_questions) == 2
    assert "差评品类" in result.sub_questions[0]
    assert "原因" in result.sub_questions[1]


def test_router_pending_sql():
    state = {
        "sub_questions": ["问题A？", "问题B？"],
        "sql_runs": [],
        "agents_done": {},
    }
    decision = route_next_rule(state)
    assert decision.next_agent == "data_analysis"


def test_router_synthesize_after_sql_done():
    state = {
        "user_query": "2017年哪个州的销售额最高？",
        "intent": "descriptive",
        "sub_questions": ["2017年哪个州的销售额最高？"],
        "sql_runs": [{"question": "2017年哪个州的销售额最高？"}],
        "agents_done": {
            "data_analysis": True,
            "visualization": True,
        },
    }
    decision = route_next_rule(state)
    assert decision.next_agent == "synthesize"


def test_router_decision_only_what_if_skips_sql():
    state = {
        "user_query": "如果 GMV 基线 100 万、转化提升 10%，GMV 会怎样？",
        "intent": "what_if",
        "sub_questions": [],
        "suggested_agents": ["decision"],
        "sql_runs": [],
        "agents_done": {},
    }
    decision = route_next_rule(state)
    assert decision.next_agent == "decision"
