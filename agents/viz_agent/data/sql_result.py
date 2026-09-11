"""查数 JSON → 出图输入：选 CSV、拼单图 execute_sql_json、合并 charts。"""

from __future__ import annotations

import json
from typing import Any

from agents.viz_agent.plan.line_plan import column_is_category, column_is_time
from agents.viz_agent.plan.viz_planner import (
    _parse_columns_from_summary_zh,
    _read_csv_header_columns,
    build_column_profiles_for_viz,
)


def pick_viz_csv_from_exec_payload(
    exec_payload: dict[str, Any],
    *,
    sql_result_index: int | None = None,
    chart_type_hint: str | None = None,
) -> str | None:
    """从 execute_sql JSON 的 results[] 里挑一条 CSV。

    指定 sql_result_index 则用该条；否则 bar 偏类别表、line 偏带时间列的表，默认取行数最多的。
    """
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
        has_time = any(column_is_time(c) for c in cols)
        has_category = any(column_is_category(c) for c in cols)
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
    """构造单图渲染可识别的 execute_sql_json（顶层含 result_csv_path）。"""
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
    """多张单图输出压成对外 charts[] + summary_text。Dashboard 只读这里的 image_path。"""
    charts: list[dict[str, Any]] = []
    ok_count = 0
    type_counts: dict[str, int] = {}
    for item in items:
        if not item:
            continue
        plan = item.get("plan") or {}
        if not isinstance(plan, dict) and hasattr(plan, "model_dump"):
            plan = plan.model_dump()
        if item.get("ok"):
            ok_count += 1
            ctype = str(
                item.get("chart_type_resolved")
                or plan.get("chart_type")
                or ""
            )
            if ctype:
                type_counts[ctype] = type_counts.get(ctype, 0) + 1
        charts.append(
            {
                "ok": item.get("ok"),
                "chart_id": item.get("chart_id"),
                "preset": item.get("preset"),
                "chart_type": item.get("chart_type_resolved") or plan.get("chart_type"),
                "image_path": item.get("image_path"),
                "csv_path": item.get("csv_path"),
                "title": plan.get("title"),
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
