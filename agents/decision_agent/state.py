"""
Decision Intelligence Agent 的共享 State 类型与 sql_results 摘要工具。

LangGraph 上各 Agent 通过 `AgentState` 共享中间结果。
Decision Agent 主要读取 question / intent / sql_results / analysis_summary /
chart_paths / chart_descriptions，写入 forecast_result / review_insights /
what_if_result / decision_report / final_answer。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, TypedDict


class SqlResultItem(TypedDict, total=False):
    name: str
    sql: str
    explanation: str
    columns: list[str]
    row_count: int
    csv_path: str
    sample_rows: list[dict[str, Any]]


class AgentState(TypedDict, total=False):
    question: str
    intent: str
    plan: list[str]

    sql_results: list[SqlResultItem]
    analysis_summary: str

    chart_paths: list[str]
    chart_descriptions: list[str]

    forecast_result: dict[str, Any] | None
    review_insights: dict[str, Any] | None
    what_if_result: dict[str, Any] | None

    decision_report: str
    final_answer: str

    conversation_history: list[dict[str, str]]


def _read_csv_head(csv_path: str, max_rows: int = 20) -> tuple[list[str], list[dict[str, Any]]]:
    """读取 CSV 头几行，用于把 SQL 结果摘要喂给 LLM。失败时返回空。"""
    p = Path(csv_path)
    if not p.exists():
        return [], []
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = list(reader.fieldnames or [])
        rows: list[dict[str, Any]] = []
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            rows.append(dict(row))
    return cols, rows


def summarize_sql_results(
    sql_results: list[SqlResultItem] | None,
    sample_rows_per_item: int = 10,
) -> list[dict[str, Any]]:
    """把 sql_results 压缩为 LLM 友好的摘要列表（避免把完整 CSV 塞进上下文）。"""
    if not sql_results:
        return []
    out: list[dict[str, Any]] = []
    for item in sql_results:
        cols = list(item.get("columns") or [])
        sample = list(item.get("sample_rows") or [])
        # 若 Data Analysis Agent 仅给了 csv_path，按需读出表头与前若干行
        csv_path = item.get("csv_path") or ""
        if csv_path and (not cols or not sample):
            file_cols, file_rows = _read_csv_head(csv_path, sample_rows_per_item)
            cols = cols or file_cols
            sample = sample or file_rows
        out.append(
            {
                "name": item.get("name", ""),
                "explanation": item.get("explanation", ""),
                "columns": cols,
                "row_count": int(item.get("row_count", len(sample))),
                "sample_rows": sample[:sample_rows_per_item],
            }
        )
    return out
