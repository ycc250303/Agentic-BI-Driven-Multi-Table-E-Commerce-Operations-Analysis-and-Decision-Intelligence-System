"""从 execute_sql JSON / CSV 解析列名与是否单值 KPI，供规划与出图共用。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agents.viz_agent.plan.line_plan import column_is_category, column_is_time

_TEXT_COLUMN_HINTS = (
    "review_comment",
    "comment_message",
    "comment_title",
    "message",
    "text",
    "评论",
    "content",
    "body",
)
_METRIC_COLUMN_MARKERS = ("_count", "_rate", "_score", "_id", "_amount", "_total")


def _parse_columns_from_summary_zh(summary_zh: str) -> list[str]:
    """从 execute_sql 的 data_summary_zh 解析列名（无 column_profiles 时的兜底）。"""
    text = summary_zh or ""
    m = re.search(r"共\s*\d+\s*列[：:]\s*([^。\n]+)", text)
    if not m:
        return []
    raw = m.group(1).replace(" …", "").strip()
    return [c.strip() for c in raw.split(",") if c.strip()]


def _read_csv_header_columns(csv_path: str | None) -> list[str]:
    if not csv_path:
        return []
    path = Path(csv_path)
    if not path.is_file():
        return []
    try:
        import pandas as pd

        return [str(c) for c in pd.read_csv(path, nrows=0).columns]
    except Exception:
        return []


def extract_columns_from_exec_payload(payload: dict[str, Any]) -> list[str]:
    """从 execute_sql JSON（含 results[]）提取列名，供规划与出图共用。"""
    profiles = payload.get("column_profiles") or []
    if profiles:
        return [str(p.get("name")) for p in profiles if p.get("name")]

    cols = _parse_columns_from_summary_zh(str(payload.get("data_summary_zh") or ""))
    if cols:
        return cols

    results = payload.get("results") or []
    if results:
        row0 = results[0]
        cols = _parse_columns_from_summary_zh(str(row0.get("data_summary_zh") or ""))
        if cols:
            return cols
        cols = _read_csv_header_columns(str(row0.get("result_csv_path") or ""))
        if cols:
            return cols

    return _read_csv_header_columns(str(payload.get("result_csv_path") or ""))


def build_column_profiles_for_viz(
    payload: dict[str, Any], row: dict[str, Any]
) -> list[dict[str, Any]]:
    """为 viz_agent 构造列画像（execute_sql 新版 JSON 无顶层 column_profiles 时）。"""
    existing = payload.get("column_profiles") or []
    if existing:
        return list(existing)

    cols = extract_columns_from_exec_payload(payload)
    if not cols:
        cols = _read_csv_header_columns(str(row.get("result_csv_path") or ""))
    return [{"name": c, "inferred_type": "unknown", "non_null_count": 0} for c in cols]


def _summarize_sql_runs(sql_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for i, run in enumerate(sql_runs):
        ar = run.get("analysis_result") or {}
        exec_json = run.get("execute_sql_json") or ""
        cols: list[str] = []
        row_count = 0
        summary_zh = ""
        ok = False
        if exec_json.strip():
            try:
                payload = json.loads(exec_json)
                ok = bool(payload.get("ok"))
                summary_zh = str(payload.get("data_summary_zh") or "")
                cols = extract_columns_from_exec_payload(payload)
                row_count = int(payload.get("row_count_returned") or 0)
                if not row_count and payload.get("results"):
                    row_count = int((payload["results"][0] or {}).get("row_count_returned") or 0)
            except json.JSONDecodeError:
                pass
        summaries.append(
            {
                "index": i,
                "question": run.get("question"),
                "ok": ok,
                "business_summary": ar.get("business_summary"),
                "data_summary_zh": summary_zh,
                "columns": cols,
                "row_count": row_count,
                "views_used": (ar.get("sql_meta") or {}).get("candidate_views"),
            }
        )
    return summaries


def _is_metric_column(col: str) -> bool:
    cl = col.lower()
    return any(m in cl for m in _METRIC_COLUMN_MARKERS) or cl.startswith("bad_review_")


def _has_text_column(cols: list[str]) -> bool:
    return any(
        not _is_metric_column(c) and any(h in c.lower() for h in _TEXT_COLUMN_HINTS)
        for c in cols
    )


def _cols_for_sql_run(
    sql_runs: list[dict[str, Any]] | None, index: int | None
) -> list[str]:
    if not sql_runs or index is None or index < 0 or index >= len(sql_runs):
        return []
    return _summarize_sql_runs([sql_runs[index]])[0].get("columns") or []


def _result_columns(row: dict[str, Any]) -> list[str]:
    cols = _parse_columns_from_summary_zh(str(row.get("data_summary_zh") or ""))
    if cols:
        return cols
    return _read_csv_header_columns(str(row.get("result_csv_path") or ""))


def _sql_result_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = [
        r for r in (payload.get("results") or []) if r.get("ok") and r.get("result_csv_path")
    ]
    if results:
        return results
    top_path = payload.get("result_csv_path")
    if top_path:
        return [
            {
                "result_csv_path": top_path,
                "row_count_returned": payload.get("row_count_returned"),
                "data_summary_zh": payload.get("data_summary_zh"),
            }
        ]
    return []


def _sql_run_payload(sql_runs: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    if index < 0 or index >= len(sql_runs):
        return None
    exec_json = str(sql_runs[index].get("execute_sql_json") or "").strip()
    if not exec_json:
        return None
    try:
        payload = json.loads(exec_json)
    except json.JSONDecodeError:
        return None
    if not payload.get("ok"):
        return None
    return payload


def _is_scalar_kpi_result(row: dict[str, Any]) -> bool:
    row_count = int(row.get("row_count_returned") or 0)
    if row_count != 1:
        return False
    cols = _result_columns(row)
    if not cols:
        return False
    if len(cols) == 1:
        return True
    if any(column_is_time(c) or column_is_category(c) for c in cols):
        return False
    return True
