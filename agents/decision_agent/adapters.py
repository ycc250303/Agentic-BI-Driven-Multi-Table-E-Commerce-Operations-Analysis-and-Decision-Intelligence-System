from __future__ import annotations

"""Boundary adapters for legacy state and upstream agent payloads.

Core Decision-Agent execution uses `DecisionInputs`. This module is the only
place that should understand historical state keys such as `analysis_summary`,
`review_insights`, or `chart_result`.
"""

from copy import deepcopy
from typing import Any

from .schemas import DecisionInputs, DecisionResult
from .state import BIState


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _pick_first(source: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


def normalize_analysis_result(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = deepcopy(raw or {})
    if not source:
        return {}

    kpis = source.get("kpis") or {}
    if not kpis:
        metric_summary = source.get("metric_summary") or source.get("metrics") or {}
        kpis = {
            "total_gmv": _pick_first(metric_summary, ["total_gmv", "gmv", "gross_merchandise_value"]),
            "total_orders": _pick_first(metric_summary, ["total_orders", "orders"]),
            "avg_basket": _pick_first(metric_summary, ["avg_basket", "average_basket"]),
            "on_time_rate": _pick_first(metric_summary, ["on_time_rate", "delivery_on_time_rate"]),
            "avg_delivery_days": _pick_first(
                metric_summary, ["avg_delivery_days", "average_delivery_days"]
            ),
            "avg_review_score": _pick_first(metric_summary, ["avg_review_score", "review_score"]),
        }

    findings = source.get("findings")
    if findings is None:
        findings = source.get("diagnostic_findings") or source.get("insights") or []

    tables = source.get("tables")
    if tables is None:
        result_table = source.get("result_table") or source.get("tables_meta")
        tables = _as_list(result_table)

    simulation_inputs = source.get("simulation_inputs") or source.get("what_if_inputs") or {}

    return {
        "summary_text": str(
            _pick_first(source, ["summary_text", "summary", "analysis_summary"], "")
        ),
        "kpis": kpis,
        "findings": findings,
        "tables": tables,
        "simulation_inputs": simulation_inputs,
    }


def normalize_nlp_result(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = deepcopy(raw or {})
    if not source:
        return {}
    # 优先用 BERTopic 无监督主题（无 other 盲区），回退到关键词 topic_distribution
    bertopic_topics = source.get("topics_bertopic") or {}
    if bertopic_topics.get("topics"):
        negative_topics = [
            {
                "topic": str(t.get("label") or f"topic_{t.get('topic_id', '')}"),
                "count": int(t.get("sample_count") or 0),
                "share": 0.0,
                "top_words": t.get("top_words") or [],
            }
            for t in bertopic_topics.get("topics") or []
        ]
        total = sum(t["count"] for t in negative_topics)
        for t in negative_topics:
            t["share"] = round(t["count"] / total, 4) if total else 0.0
    else:
        negative_topics = _pick_first(
            source, ["negative_topics", "topic_distribution", "complaint_topics"], []
        )
        if isinstance(negative_topics, dict):
            total = sum(
                value for value in negative_topics.values() if isinstance(value, int | float)
            )
            negative_topics = [
                {
                    "topic": str(topic),
                    "count": int(count),
                    "share": float(count) / total if total else 0.0,
                }
                for topic, count in negative_topics.items()
                if isinstance(count, int | float)
            ]

    # 优先用 BERTopic complaints_by_category（更细粒度），回退关键词版
    bertopic_complaints = bertopic_topics.get("complaints_by_category") or []
    worst_categories_keyword = _pick_first(
        source, ["worst_categories", "complaints_by_category"], []
    )
    if bertopic_complaints:
        worst_categories = [
            {
                "category": item.get("category") or "unknown",
                "negative_count": int(item.get("total") or 0),
                "dominant_topic": (
                    item["top_reasons"][0]["label"]
                    if item.get("top_reasons") and len(item["top_reasons"]) > 0
                    else ""
                ),
                "dominant_share": (
                    float(item["top_reasons"][0].get("share", 0))
                    if item.get("top_reasons") and len(item["top_reasons"]) > 0
                    else 0.0
                ),
                "top_reasons": item.get("top_reasons") or [],
            }
            for item in bertopic_complaints
            if isinstance(item, dict)
        ]
    elif isinstance(worst_categories_keyword, list):
        worst_categories = worst_categories_keyword
    else:
        worst_categories = []

    if isinstance(worst_categories, list):
        normalized_categories = []
        for item in worst_categories:
            if not isinstance(item, dict):
                continue
            total = float(item.get("total") or item.get("count") or 0.0)
            dominant_share = float(item.get("dominant_share") or 0.0)
            normalized_categories.append(
                {
                    "category": item.get("category") or item.get("key") or "unknown",
                    "negative_rate": item.get("negative_rate")
                    if item.get("negative_rate") is not None
                    else dominant_share,
                    "negative_count": int(total),
                    "dominant_topic": item.get("dominant_topic"),
                }
            )
        worst_categories = normalized_categories

    worst_states = _pick_first(source, ["worst_states", "complaints_by_state"], [])
    if not worst_states and isinstance(source.get("top_customer_states"), list):
        top_states = source.get("top_customer_states") or []
        total = sum(
            item.get("count", 0)
            for item in top_states
            if isinstance(item, dict) and isinstance(item.get("count"), int | float)
        )
        worst_states = [
            {
                "state": item.get("key"),
                "negative_rate": float(item.get("count") or 0) / total if total else 0.0,
                "negative_count": item.get("count"),
            }
            for item in top_states
            if isinstance(item, dict)
        ]

    sentiment = _pick_first(
        source, ["sentiment_overview", "sentiment", "sentiment_summary"], {}
    )
    if isinstance(sentiment, dict) and sentiment.get("method") == "n/a":
        sentiment = {"summary": sentiment.get("summary", "")}

    # 优先用 BERTopic summary（无 other 盲区），回退关键词 summary
    bertopic_summary = bertopic_topics.get("summary") or ""
    return {
        "summary_text": str(
            bertopic_summary
            or _pick_first(source, ["summary_text", "summary", "review_summary"], "")
        ),
        "negative_topics": negative_topics,
        "worst_categories": worst_categories,
        "worst_states": worst_states,
        "sentiment_overview": sentiment,
    }


def normalize_what_if_result(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = deepcopy(raw or {})
    if not source:
        return {}
    if "scenario_type" in source:
        return source
    if "current_avg_score" in source and "simulated_avg_score" in source:
        return {
            "scenario_type": "remove_top_bad_sellers",
            "parameters": {
                "top_n": source.get("top_n"),
                "min_reviews_filter": source.get("min_reviews_filter"),
            },
            "baseline_metrics": {
                "avg_review_score": source.get("current_avg_score"),
                "negative_rate": source.get("current_negative_rate"),
                "total_reviews": source.get("total_reviews"),
            },
            "simulated_metrics": {
                "avg_review_score": source.get("simulated_avg_score"),
                "negative_rate": source.get("simulated_negative_rate"),
                "removed_reviews": source.get("removed_reviews"),
            },
            "delta_metrics": {
                "avg_review_score": source.get("estimated_score_improvement"),
                "negative_rate": -float(source.get("estimated_negative_rate_drop") or 0.0),
            },
            "summary_text": str(source.get("summary") or ""),
        }
    return source


def normalize_forecast_result(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = deepcopy(raw or {})
    if not source:
        return {}
    return {
        "summary_text": str(
            _pick_first(source, ["summary_text", "summary", "forecast_summary"], "")
        ),
        "horizon": _pick_first(source, ["horizon", "forecast_horizon"], ""),
        "forecast_values": _pick_first(
            source, ["forecast_values", "values", "predictions"], []
        ),
        "trend_direction": str(
            _pick_first(source, ["trend_direction", "trend", "direction"], "")
        ),
        "risk_flags": _pick_first(source, ["risk_flags", "warnings", "alerts"], []),
    }


def normalize_visualization_result(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = deepcopy(raw or {})
    if not source:
        return {}
    return {
        "summary_text": str(
            _pick_first(source, ["summary_text", "summary", "chart_summary"], "")
        ),
        "charts": _pick_first(source, ["charts", "items", "figures"], []),
    }


def normalize_state(state: dict[str, Any]) -> BIState:
    """Normalize legacy/orchestrator state into the current compatibility shape."""
    normalized = dict(state)
    normalized["analysis_result"] = normalize_analysis_result(
        state.get("analysis_result") or state.get("analysis_summary")
    )
    normalized["nlp_result"] = normalize_nlp_result(
        state.get("nlp_result") or state.get("review_insights")
    )
    normalized["forecast_result"] = normalize_forecast_result(
        state.get("forecast_result") or state.get("forecast_summary")
    )
    normalized["visualization_result"] = normalize_visualization_result(
        state.get("visualization_result") or state.get("chart_result")
    )
    normalized["what_if_result"] = normalize_what_if_result(state.get("what_if_result"))
    normalized["conversation_history"] = _as_list(state.get("conversation_history"))
    normalized["warnings"] = _as_list(state.get("warnings"))
    return normalized


def decision_inputs_from_state(state: dict[str, Any]) -> DecisionInputs:
    """Convert compatibility state into the core `DecisionInputs` contract."""
    normalized = normalize_state(state)
    return DecisionInputs(
        user_query=str(normalized.get("user_query") or ""),
        intent=str(normalized.get("intent") or "prescriptive"),
        analysis_result=normalized.get("analysis_result") or {},
        nlp_result=normalized.get("nlp_result") or {},
        forecast_result=normalized.get("forecast_result") or {},
        visualization_result=normalized.get("visualization_result") or {},
        what_if_result=normalized.get("what_if_result") or {},
        conversation_history=normalized.get("conversation_history") or [],
    )


def merge_decision_result_to_state(
    state: dict[str, Any],
    decision_result: DecisionResult,
    *,
    warnings: list[str] | None = None,
) -> BIState:
    """Write a `DecisionResult` back to compatibility state fields."""
    next_state = dict(state)
    next_state["decision_result"] = decision_result.model_dump(mode="json")
    next_state["final_answer"] = decision_result.narrative_answer
    if warnings is not None:
        next_state["warnings"] = list(warnings)
    return next_state
