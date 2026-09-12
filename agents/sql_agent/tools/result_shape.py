"""标量子问题的执行行数形状检查。不连库、不调 LLM。"""

from __future__ import annotations

import json
import re
from typing import Any

_TOP_N_RE = re.compile(r"^top(\d+)$", re.IGNORECASE)
_SCALAR_AGG_SKIP = frozenset({"trend", "share"})


def _load_dict(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def is_scalar_subquestion(sub: dict[str, Any]) -> bool:
    """无分析维度、且不是 topN/trend/share 的子问题，按全表标量（恰好 1 行）处理。"""
    dims = [str(d).strip() for d in (sub.get("dimensions") or []) if str(d).strip()]
    if dims:
        return False
    agg = str(sub.get("aggregation") or "").strip().lower()
    if _TOP_N_RE.match(agg) or agg in _SCALAR_AGG_SKIP:
        return False
    return True


def scalar_result_shape_brief(rewrite_json: str, execute_sql_json: str) -> str:
    """标量子问题应对齐 1 行执行结果。空字符串表示无需据此重试。"""
    plan = _load_dict(rewrite_json)
    execd = _load_dict(execute_sql_json)
    if plan is None or execd is None:
        return ""
    subs = plan.get("sub_questions") or []
    if not isinstance(subs, list) or not subs:
        return ""
    results = execd.get("results") or []
    if not isinstance(results, list):
        return ""
    issues: list[str] = []
    for i, sub in enumerate(subs):
        if not isinstance(sub, dict) or not is_scalar_subquestion(sub):
            continue
        row = results[i] if i < len(results) and isinstance(results[i], dict) else None
        if row is None:
            issues.append(f"query_sqls[{i}] 计划为全表标量（1 行），执行结果缺失")
            continue
        if row.get("ok") is not True:
            continue
        n = int(row.get("row_count_returned") or 0)
        if n != 1:
            issues.append(
                f"query_sqls[{i}] 计划为全表标量（dimensions 为空且非 topN），"
                f"实际返回 {n} 行；不要扫明细或 GROUP BY 维度，应汇总成恰好 1 行"
            )
    return "；".join(issues)
