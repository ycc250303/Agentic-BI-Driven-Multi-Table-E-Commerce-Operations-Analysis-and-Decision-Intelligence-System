"""多轮会话：继承会话级 NLP 缓存，确保追问能用到上一轮评论洞察。"""

from __future__ import annotations

from typing import Any

from agents.coordinator_agent.planner import classify_intent
from agents.nlp_agent.run import should_run_nlp


def _has_review_insights(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    return bool(
        data.get("summary")
        or data.get("summary_text")
        or data.get("topic_distribution")
        or data.get("topics_bertopic")
        or data.get("wordcloud")
    )


def _insights_from_session(session: dict[str, Any]) -> dict[str, Any] | None:
    cached = session.get("review_insights")
    if _has_review_insights(cached):
        return cached

    turns = session.get("turns") or []
    for turn in reversed(turns):
        state = turn.get("state") or {}
        insights = state.get("review_insights") or state.get("nlp_result")
        if _has_review_insights(insights):
            return insights
    return None


def seed_state_from_session(
    session: dict[str, Any],
    *,
    resolved_task: str,
    full_state: bool,
) -> dict[str, Any]:
    """为新一轮协调器注入会话内已有的 review_insights。"""
    _ = full_state  # 会话级缓存不依赖 full_state
    insights = _insights_from_session(session)
    if not insights:
        return {}

    intent = classify_intent(resolved_task)
    if not should_run_nlp(resolved_task, intent):
        return {}

    return {
        "review_insights": insights,
        "nlp_result": insights,
    }
