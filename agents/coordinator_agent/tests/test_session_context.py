from __future__ import annotations

from agents.coordinator_agent.session_context import seed_state_from_session


def test_seed_review_insights_from_session_cache():
    session = {
        "review_insights": {
            "summary": "配送延迟是主要差评主题",
            "topic_distribution": {"delivery_delay": 100},
        }
    }
    patch = seed_state_from_session(
        session,
        resolved_task="预测未来各品类差评订单数变化趋势",
        full_state=False,
    )
    assert patch["review_insights"]["summary"].startswith("配送")
    assert patch["nlp_result"] == patch["review_insights"]


def test_no_seed_when_query_does_not_need_nlp():
    session = {
        "review_insights": {"summary": "配送延迟是主要差评主题"},
    }
    assert (
        seed_state_from_session(
            session,
            resolved_task="2017 年 GMV 是多少？",
            full_state=False,
        )
        == {}
    )
