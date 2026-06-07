"""折线图规划归一化：补全 x/y/分系列列，避免渲染层误判为单线。"""

from __future__ import annotations

import pandas as pd

from agents.viz_agent.schema import VizPlan

_TIME_HINTS = ("month", "date", "year", "timestamp", "week", "day", "period", "时间")
_CATEGORY_HINTS = (
    "state",
    "category",
    "region",
    "city",
    "customer",
    "product",
    "payment",
    "seller",
    "segment",
    "州",
    "品类",
    "地区",
)


def _is_time_col(name: str) -> bool:
    cl = (name or "").lower()
    return any(h in cl for h in _TIME_HINTS)


def _is_category_col(name: str) -> bool:
    cl = (name or "").lower()
    return any(h in cl for h in _CATEGORY_HINTS)


def infer_line_series_column(
    df: pd.DataFrame,
    x_column: str | None,
    y_column: str | None,
) -> str | None:
    """推断分系列列（如 customer_state）；无合适列时返回 None。"""
    candidates: list[tuple[int, int, str]] = []
    for col in df.columns:
        if col in (x_column, y_column):
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            continue
        n = int(df[col].nunique(dropna=True))
        if n < 2 or n > 50:
            continue
        score = 1 + (10 if _is_category_col(col) else 0)
        candidates.append((score, n, col))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def normalize_line_plan(df: pd.DataFrame, plan: VizPlan) -> VizPlan:
    """补全/修正 line 计划的列映射，含多系列 category_column。"""
    if plan.chart_type != "line":
        return plan

    cols = list(df.columns)
    nums = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    time_cols = [c for c in cols if _is_time_col(c)]
    cat_cols = [
        c for c in cols if not pd.api.types.is_numeric_dtype(c) and c not in time_cols
    ]

    x_c = plan.x_column if plan.x_column in cols else None
    if not x_c and time_cols:
        x_c = time_cols[0]

    y_c = plan.y_column if plan.y_column in cols else None
    if not y_c and nums:
        y_c = nums[0]

    series = plan.category_column or plan.hue_column
    if not series or series not in cols or series in (x_c, y_c):
        series = infer_line_series_column(df, x_c, y_c)

    if not x_c or not y_c:
        return plan

    updates: dict[str, str | None] = {"x_column": x_c, "y_column": y_c}
    if series:
        updates["category_column"] = series
    return plan.model_copy(update=updates)
