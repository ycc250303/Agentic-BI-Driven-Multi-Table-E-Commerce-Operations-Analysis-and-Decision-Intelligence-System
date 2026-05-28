from __future__ import annotations

from copy import deepcopy
from typing import Any

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
    return {
        "summary_text": str(
            _pick_first(source, ["summary_text", "summary", "review_summary"], "")
        ),
        "negative_topics": _pick_first(
            source, ["negative_topics", "topic_distribution", "complaint_topics"], []
        ),
        "worst_categories": _pick_first(
            source, ["worst_categories", "complaints_by_category"], []
        ),
        "worst_states": _pick_first(source, ["worst_states", "complaints_by_state"], []),
        "sentiment_overview": _pick_first(
            source, ["sentiment_overview", "sentiment", "sentiment_summary"], {}
        ),
    }


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
    normalized["conversation_history"] = _as_list(state.get("conversation_history"))
    normalized["warnings"] = _as_list(state.get("warnings"))
    return normalized
