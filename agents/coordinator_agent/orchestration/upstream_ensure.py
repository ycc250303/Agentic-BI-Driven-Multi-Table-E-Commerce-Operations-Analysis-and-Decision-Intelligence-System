"""决策前强制补齐上游 Agent 应产出的 nlp_result / forecast_result。"""

from __future__ import annotations

from typing import Any

from agents.decision_agent.adapters import normalize_nlp_result
from agents.decision_agent.forecast_from_analysis import (
    build_bad_review_forecast_result,
    try_build_gmv_forecast_result,
)
from agents.decision_agent.warning_policy import has_forecast_payload, has_nlp_payload
from agents.nlp_agent.run import ReviewInsightAgent, should_run_nlp


def _nlp_expected(state: dict[str, Any]) -> bool:
    query = str(state.get("user_query") or "")
    intent = str(state.get("intent") or "")
    if should_run_nlp(query, intent):
        return True
    suggested = state.get("suggested_agents") or []
    done = state.get("agents_done") or {}
    return "nlp" in suggested or bool(done.get("nlp"))


def _forecast_expected(state: dict[str, Any]) -> bool:
    return str(state.get("intent") or "") == "predictive"


def _ensure_nlp(state: dict[str, Any]) -> dict[str, Any]:
    if not _nlp_expected(state):
        return {}
    existing = normalize_nlp_result(
        state.get("review_insights") or state.get("nlp_result")
    )
    if has_nlp_payload(existing):
        patch: dict[str, Any] = {}
        if state.get("review_insights") and not state.get("nlp_result"):
            patch["nlp_result"] = state["review_insights"]
        elif state.get("nlp_result") and not state.get("review_insights"):
            patch["review_insights"] = state["nlp_result"]
        return patch

    agent = ReviewInsightAgent()
    out = agent.run(dict(state))
    insights = out.get("review_insights") or {}
    if not has_nlp_payload(normalize_nlp_result(insights)):
        return {}
    done = dict(state.get("agents_done") or {})
    done["nlp"] = True
    return {
        "review_insights": insights,
        "nlp_result": insights,
        "agents_done": done,
    }


def _ensure_forecast(state: dict[str, Any]) -> dict[str, Any]:
    if not _forecast_expected(state):
        return {}
    if has_forecast_payload(state.get("forecast_result") or {}):
        return {"_forecast_attempted": True}

    user_query = str(state.get("user_query") or "")
    intent = str(state.get("intent") or "")
    sql_runs = state.get("sql_runs") or []

    built = build_bad_review_forecast_result(
        user_query=user_query,
        intent=intent,
        sql_runs=sql_runs,
    )
    if built:
        return {"forecast_result": built, "_forecast_attempted": True}

    gmv_fc = try_build_gmv_forecast_result()
    if gmv_fc:
        return {"forecast_result": gmv_fc, "_forecast_attempted": True}

    return {"_forecast_attempted": True}


def ensure_upstream_payloads(state: dict[str, Any]) -> dict[str, Any]:
    """在决策 Agent 运行前补齐缺失的 NLP / 预测结果。"""
    patch: dict[str, Any] = {}
    patch.update(_ensure_nlp(state))
    merged = {**state, **patch}
    patch.update(_ensure_forecast(merged))
    return patch
