"""对照 rewrite 计划与 generate SQL 的确定性检查。不连库、不调 LLM。"""

from __future__ import annotations

import json
import re
from typing import Any

_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)
_NESTED_SELECT_RE = re.compile(r"\(\s*SELECT\b", re.IGNORECASE)
_TOP_N_RE = re.compile(r"^top(\d+)$", re.IGNORECASE)
_HAVING_RE = re.compile(r"\bHAVING\b", re.IGNORECASE)


def _load_dict(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _query_sqls(generate_sql_json: str) -> list[str]:
    data = _load_dict(generate_sql_json)
    if data is None:
        return []
    sqls = data.get("query_sqls") or []
    return [str(s).strip() for s in sqls if str(s).strip()]


def _outer_sql(sql: str) -> str:
    """去掉括号内子查询 / 函数参数，只保留最外层子句（用于检查 LIMIT）。"""
    s = sql
    while True:
        nxt = re.sub(r"\([^()]*\)", " ", s)
        if nxt == s:
            return s
        s = nxt


def plan_sql_consistency(
    rewrite_json: str, generate_sql_json: str
) -> tuple[bool, str]:
    """计划字段与 SQL 是否明显打架。无 sub_questions 时放行（跳过 rewrite 的消融臂）。"""
    plan = _load_dict(rewrite_json)
    if plan is None:
        return True, ""
    subs = plan.get("sub_questions") or []
    if not isinstance(subs, list) or not subs:
        return True, ""

    sqls = _query_sqls(generate_sql_json)
    if not sqls:
        return False, "query_sqls 为空，无法对照计划"

    if len(sqls) != len(subs):
        return (
            False,
            "计划与 SQL 不一致："
            f"query_sqls 条数 {len(sqls)} 与 sub_questions 条数 {len(subs)} 不一致，"
            "必须一条子问题一条 SQL",
        )

    issues: list[str] = []
    for i, (sub, sql) in enumerate(zip(subs, sqls)):
        sub = sub if isinstance(sub, dict) else {}
        issues.extend(_check_one(i, sub, sql))

    if issues:
        return False, "计划与 SQL 不一致：" + "；".join(issues)
    return True, ""


def _check_one(index: int, sub: dict[str, Any], sql: str) -> list[str]:
    issues: list[str] = []
    agg = str(sub.get("aggregation") or "").strip()
    metric = str(sub.get("metric_key") or "").strip().lower()
    scope = sub.get("scope") if isinstance(sub.get("scope"), dict) else {}
    kind = str(scope.get("kind") or "")
    outer = _outer_sql(sql)

    top = _TOP_N_RE.match(agg)
    found = _LIMIT_RE.search(outer)
    if top:
        k = int(top.group(1))
        if found is None:
            issues.append(f"query_sqls[{index}] aggregation={agg} 但缺少外层 LIMIT {k}")
        else:
            got = int(found.group(1))
            if got != k:
                issues.append(
                    f"query_sqls[{index}] 外层 LIMIT {got} 与 aggregation top{k} 不一致"
                )
    elif found is not None:
        got = int(found.group(1))
        issues.append(
            f"query_sqls[{index}] 非 topN 子问题不要外层 LIMIT {got}；"
            "分布/对比/趋势请输出全部分组，用 ORDER BY 表示排序"
        )

    if not top and _HAVING_RE.search(outer):
        issues.append(
            f"query_sqls[{index}] 非 topN 不要外层 HAVING；"
            "列出全部分组时不要用样本量门槛丢掉小样本"
        )

    if kind == "inherit_previous" and not _NESTED_SELECT_RE.search(sql):
        inherited = str(scope.get("inherit_from") or "前序子问题")
        issues.append(
            f"query_sqls[{index}] 须继承 {inherited}，用子查询绑定过滤对象，禁止改成全平台"
        )

    if metric in {"on_time_rate", "delay_rate"} and kind == "platform":
        sql_l = sql.lower()
        uses_view = "mv_delivery_perf" in sql_l
        uses_orders = re.search(r"(?:from|join)\s+`?orders`?", sql_l) is not None
        if uses_view and not uses_orders:
            issues.append(
                f"query_sqls[{index}] 平台级准时/延迟率 grain 是订单，"
                "不得只扫 mv_delivery_perf；请回退 `orders` 按订单重算"
            )

    if metric.endswith("_rate") and top and not _HAVING_RE.search(sql):
        issues.append(
            f"query_sqls[{index}] 比率排名须 HAVING 过滤分组样本量，"
            "避免极小样本把率冲到极端"
        )

    issues.extend(_check_measure_keys(index, sub, sql))
    issues.extend(_check_freight_not_on_sales_view(index, metric, sub, sql))

    return issues


_MEASURE_HINTS: dict[str, tuple[str, ...]] = {
    "gmv_total": ("total_gmv", "gmv"),
    "total_gmv": ("total_gmv", "gmv"),
    "total_orders": ("total_orders", "order_count"),
    "avg_basket": ("avg_basket", "aov"),
    "avg_price": ("avg_price",),
    "on_time_rate": ("on_time_rate",),
    "avg_installments": ("avg_installments",),
    "freight_share": ("freight_share", "freight_value"),
    "gmv_2017": ("gmv_2017", "2017"),
    "gmv_2018": ("gmv_2018", "2018"),
}


def _check_measure_keys(index: int, sub: dict[str, Any], sql: str) -> list[str]:
    keys = sub.get("measure_keys") or []
    if not isinstance(keys, list) or not keys:
        return []
    sql_l = sql.lower()
    missing: list[str] = []
    for raw in keys:
        mk = str(raw).strip().lower()
        if not mk:
            continue
        tokens = _MEASURE_HINTS.get(mk, (mk,))
        if not any(tok in sql_l for tok in tokens):
            missing.append(mk)
    if not missing:
        return []
    return [
        f"query_sqls[{index}] measure_keys 缺少列 {missing}，同一子问题的多个度量须写在同一条 SQL"
    ]


def _check_freight_not_on_sales_view(
    index: int, metric: str, sub: dict[str, Any], sql: str
) -> list[str]:
    keys = [str(k).lower() for k in (sub.get("measure_keys") or [])]
    blob = " ".join([metric, *keys])
    if "freight" not in blob:
        return []
    sql_l = sql.lower()
    uses_items = "order_items" in sql_l or "freight_value" in sql_l
    uses_sales_view = "mv_state_sales" in sql_l or "mv_monthly_sales" in sql_l
    if uses_sales_view and not uses_items:
        return [
            f"query_sqls[{index}] 运费相关指标不在销售视图字段中，请回退 `order_items`"
        ]
    return []
