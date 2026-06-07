from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _json_load(raw: str | None) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(str(raw))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _read_key_rows(csv_path: str | None, *, limit: int = 8) -> list[dict[str, Any]]:
    if not csv_path:
        return []
    path = Path(csv_path)
    if not path.is_file():
        return []
    try:
        df = pd.read_csv(path)
    except Exception:
        return []
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for record in df.head(limit).to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for k, v in record.items():
            if pd.isna(v):
                continue
            if hasattr(v, "item"):
                try:
                    clean[k] = v.item()
                except Exception:
                    clean[k] = v
            else:
                clean[k] = v
        if clean:
            rows.append(clean)
    return rows


def _dedupe_view_mention(explanation: str, views: list[Any]) -> str:
    text = explanation.strip()
    if not text or not views:
        return text
    view_names = ", ".join(map(str, views))
    prefix = f"命中预聚合视图：{view_names}。"
    if text.startswith(prefix):
        return text
    if "命中预聚合视图" in text:
        return text
    return f"使用预聚合视图 {view_names}。" + text


def build_analysis_result_from_sql_pipeline(
    *,
    user_query: str,
    sql_pipeline: dict[str, Any] | None,
) -> dict[str, Any]:
    """将单次 sql_agent 运行结果转为结构化证据（不含 execute 技术摘要）。"""
    pipe = sql_pipeline or {}
    exec_payload = _json_load(pipe.get("execute_sql_json"))
    gen_payload = _json_load(pipe.get("generate_sql_json"))
    rewrite_payload = _json_load(pipe.get("rewrite_json"))

    results = list(exec_payload.get("results") or [])
    tables: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []

    for row in results:
        csv_path = row.get("result_csv_path")
        rows = _read_key_rows(csv_path)
        key_rows.extend(rows)
        tables.append(
            {
                "index": row.get("index"),
                "csv_path": csv_path,
                "row_count": row.get("row_count_returned"),
                "ok": row.get("ok"),
                "key_rows": rows,
            }
        )

    rewrite_views = list(rewrite_payload.get("candidate_views") or [])
    hit_view = rewrite_payload.get("hit_pre_agg_view")
    explanation = str(gen_payload.get("result_explanation") or "").strip()
    if hit_view and rewrite_views:
        business_summary = _dedupe_view_mention(explanation, rewrite_views)
    else:
        business_summary = explanation or f"已完成「{user_query}」的数据查询。"

    findings: list[dict[str, Any]] = []
    if not exec_payload.get("ok"):
        findings.append(
            {
                "topic": "sql_execution",
                "metric": "ok",
                "scope": "pipeline",
                "value": 0,
                "evidence": str(exec_payload.get("error_message") or "SQL 执行未完全成功"),
            }
        )

    return {
        "question": user_query,
        "business_summary": business_summary,
        "summary_text": business_summary,
        "key_rows": key_rows,
        "kpis": {},
        "findings": findings,
        "tables": tables,
        "simulation_inputs": {},
        "sql_meta": {
            "hit_pre_agg_view": hit_view,
            "candidate_views": rewrite_views,
        },
    }


def merge_sql_runs(sql_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """合并多次单问题 SQL 结果为 decision_agent 的 analysis_result。"""
    if not sql_runs:
        return {}

    summaries: list[str] = []
    all_tables: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []
    all_key_rows: list[dict[str, Any]] = []

    for run in sql_runs:
        question = str(run.get("question") or "")
        ar = run.get("analysis_result") or {}
        bs = str(ar.get("business_summary") or ar.get("summary_text") or "")
        if bs:
            summaries.append(f"{question}\n{bs}")
        all_tables.extend(ar.get("tables") or [])
        all_findings.extend(ar.get("findings") or [])
        all_key_rows.extend(ar.get("key_rows") or [])

    return {
        "summary_text": "\n\n".join(summaries),
        "business_summaries": summaries,
        "key_rows": all_key_rows,
        "kpis": {},
        "findings": all_findings,
        "tables": all_tables,
        "simulation_inputs": {},
    }


def pick_viz_csv_from_exec_payload(
    exec_payload: dict[str, Any],
    *,
    sql_result_index: int | None = None,
    chart_type_hint: str | None = None,
) -> str | None:
    """从 execute_sql JSON 中选取最适合出图的一条 CSV 路径。"""
    from agents.viz_agent.viz_planner import (
        _column_is_category,
        _column_is_time,
        _parse_columns_from_summary_zh,
        _read_csv_header_columns,
    )

    results = [
        r
        for r in (exec_payload.get("results") or [])
        if r.get("ok") and r.get("result_csv_path")
    ]
    if not results:
        top_path = exec_payload.get("result_csv_path")
        if top_path:
            return str(top_path)
        return None
    if sql_result_index is not None and 0 <= sql_result_index < len(results):
        return str(results[sql_result_index]["result_csv_path"])
    if len(results) == 1:
        return str(results[0]["result_csv_path"])

    def _score_result(row: dict[str, Any], *, prefer: str) -> int:
        cols = _parse_columns_from_summary_zh(str(row.get("data_summary_zh") or ""))
        if not cols:
            cols = _read_csv_header_columns(str(row.get("result_csv_path") or ""))
        if not cols:
            cols = [
                str(p.get("name"))
                for p in (exec_payload.get("column_profiles") or [])
                if p.get("name")
            ]
        has_time = any(_column_is_time(c) for c in cols)
        has_category = any(_column_is_category(c) for c in cols)
        row_count = int(row.get("row_count_returned") or 0)
        score = row_count
        if prefer == "bar":
            if has_category and not has_time:
                score += 100_000
            if has_time:
                score -= 50_000
            if 5 <= row_count <= 40:
                score += 100
        elif prefer == "line":
            if has_time and has_category:
                score += 1000
            elif has_time:
                score += 500
            if has_category and not has_time:
                score -= 300
        return score

    prefer = "auto"
    if chart_type_hint in ("bar", "line"):
        prefer = chart_type_hint
    if prefer != "auto":
        best = max(results, key=lambda r: _score_result(r, prefer=prefer))
        return str(best["result_csv_path"])

    return str(
        max(results, key=lambda r: int(r.get("row_count_returned") or 0))["result_csv_path"]
    )


def build_viz_execute_json(exec_payload: dict[str, Any], row: dict[str, Any]) -> str:
    """构造 viz_agent 可识别的 execute_sql_json（顶层含 result_csv_path）。"""
    from agents.viz_agent.viz_planner import build_column_profiles_for_viz

    payload = {
        "ok": True,
        "executed": True,
        "result_csv_path": row.get("result_csv_path"),
        "data_summary_zh": row.get("data_summary_zh") or exec_payload.get("data_summary_zh"),
        "column_profiles": build_column_profiles_for_viz(exec_payload, row),
        "row_count_returned": row.get("row_count_returned"),
    }
    return json.dumps(payload, ensure_ascii=False)


def merge_visualization_results(items: list[dict[str, Any]]) -> dict[str, Any]:
    charts: list[dict[str, Any]] = []
    ok_count = 0
    type_counts: dict[str, int] = {}
    for item in items:
        if not item:
            continue
        if item.get("ok"):
            ok_count += 1
            ctype = str(
                item.get("chart_type_resolved")
                or ((item.get("plan") or {}).get("chart_type"))
                or ""
            )
            if ctype:
                type_counts[ctype] = type_counts.get(ctype, 0) + 1
        charts.append(
            {
                "ok": item.get("ok"),
                "chart_id": item.get("chart_id"),
                "preset": item.get("preset"),
                "chart_type": item.get("chart_type_resolved")
                or ((item.get("plan") or {}).get("chart_type")),
                "image_path": item.get("image_path"),
                "csv_path": item.get("csv_path"),
                "title": (item.get("plan") or {}).get("title"),
                "question": item.get("user_query"),
                "error_message": item.get("error_message"),
            }
        )
    distinct_types = len(type_counts)
    return {
        "summary_text": (
            f"共生成 {ok_count} 张图表，覆盖 {distinct_types} 种类型"
            f"（{', '.join(sorted(type_counts.keys())) or '无'}）。"
        ),
        "charts": charts,
        "chart_type_counts": type_counts,
    }


def build_synthesis_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """供 LLM 汇总用的干净证据包（无技术噪声）。"""
    sql_items: list[dict[str, Any]] = []
    for run in state.get("sql_runs") or []:
        ar = run.get("analysis_result") or {}
        sql_items.append(
            {
                "question": run.get("question"),
                "business_summary": ar.get("business_summary"),
                "key_rows": ar.get("key_rows") or [],
                "views_used": (ar.get("sql_meta") or {}).get("candidate_views"),
            }
        )

    viz = state.get("visualization_result") or {}
    charts = [
        {
            "title": c.get("title") or c.get("chart_type"),
            "chart_type": c.get("chart_type"),
        }
        for c in (viz.get("charts") or [])
        if c.get("ok")
    ]

    insights = state.get("review_insights") or state.get("nlp_result") or {}
    decision = state.get("decision_result") or {}

    # 优先用 BERTopic 无监督主题摘要（无 other 盲区）；若无则回退关键词 summary
    bertopic = insights.get("topics_bertopic") or {}
    bertopic_summary = bertopic.get("summary") or ""
    keyword_summary = insights.get("summary") or ""
    bertopic_topics = bertopic.get("topics") or []
    # BERTopic 各品类 × 主题下钻，可比关键词 complaints_by_category 更细
    bertopic_complaints = bertopic.get("complaints_by_category") or []

    review_summary = bertopic_summary or keyword_summary or (
        insights.get("topic_distribution") and "见差评主题分布"
    ) or ""

    forecast_raw = state.get("forecast_result") or {}
    weekly_fc = forecast_raw.get("weekly_forecast") or []
    if not weekly_fc and forecast_raw.get("periods"):
        weekly_fc = [
            {
                "week_label": forecast_raw["periods"][i],
                "forecast_gmv": (forecast_raw.get("values") or forecast_raw.get("forecast_values") or [None])[i],
                "lower_95": (forecast_raw.get("lower") or [None])[i] if i < len(forecast_raw.get("lower") or []) else None,
                "upper_95": (forecast_raw.get("upper") or [None])[i] if i < len(forecast_raw.get("upper") or []) else None,
            }
            for i in range(len(forecast_raw["periods"]))
        ]

    return {
        "user_query": state.get("user_query"),
        "intent": state.get("intent"),
        "sub_questions": state.get("sub_questions") or [],
        "sql_results": sql_items,
        "charts": charts,
        "forecast_detail": {
            "summary_text": forecast_raw.get("summary_text"),
            "method": forecast_raw.get("method"),
            "method_zh": forecast_raw.get("method_zh"),
            "horizon_weeks": forecast_raw.get("horizon_weeks"),
            "lookback_weeks": forecast_raw.get("lookback_weeks"),
            "trend_direction": forecast_raw.get("trend_direction"),
            "trend_zh": forecast_raw.get("trend_zh"),
            "last_actual_week": forecast_raw.get("last_actual_week"),
            "last_actual_gmv": forecast_raw.get("last_actual_gmv"),
            "slope_per_week": forecast_raw.get("slope_per_week"),
            "weekly_forecast": weekly_fc,
            "risk_flags": forecast_raw.get("risk_flags") or [],
        }
        if forecast_raw
        else None,
        "review_insights_summary": review_summary,
        "review_topics_bertopic": bertopic_topics,
        "review_complaints_by_category": bertopic_complaints,
        "decision_narrative": decision.get("narrative_answer") or "",
        "action_plan": decision.get("action_plan") or [],
        "warnings": state.get("warnings") or [],
    }
