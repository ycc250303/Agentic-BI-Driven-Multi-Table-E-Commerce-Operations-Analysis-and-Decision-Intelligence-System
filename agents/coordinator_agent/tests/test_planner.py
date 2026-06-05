from __future__ import annotations

from agents.coordinator_agent.decomposer import decompose_query_rule
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
