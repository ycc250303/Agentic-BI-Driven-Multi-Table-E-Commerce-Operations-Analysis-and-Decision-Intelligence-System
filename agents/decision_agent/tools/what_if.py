"""
What-if 工具：模拟「下架 Top N 高差评卖家」对平台平均评分的影响。

实现为静态反事实估计：从 order_reviews 整体样本中剔除属于 Top N 卖家（按差评率 desc，
要求样本量 >= min_reviews）的订单评论后，重新计算平均评分与差评率。
不考虑用户需求转移与替代购买行为，需在报告中明确说明。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agents.decision_agent import db


_WHAT_IF_SQL = """
WITH seller_review AS (
    SELECT
        oi.seller_id,
        COUNT(*) AS review_cnt,
        AVG(r.review_score) AS avg_score,
        SUM(CASE WHEN r.review_score <= 2 THEN 1 ELSE 0 END) / COUNT(*) AS negative_rate
    FROM order_reviews r
    JOIN order_items oi ON r.order_id = oi.order_id
    GROUP BY oi.seller_id
    HAVING review_cnt >= %s
),
top_bad_sellers AS (
    SELECT seller_id
    FROM seller_review
    ORDER BY negative_rate DESC
    LIMIT %s
)
SELECT
    AVG(r.review_score) AS current_avg_score,
    AVG(CASE WHEN oi.seller_id NOT IN (SELECT seller_id FROM top_bad_sellers)
             THEN r.review_score END) AS simulated_avg_score,
    SUM(CASE WHEN r.review_score <= 2 THEN 1 ELSE 0 END) / COUNT(*) AS current_negative_rate,
    SUM(CASE WHEN r.review_score <= 2
                 AND oi.seller_id NOT IN (SELECT seller_id FROM top_bad_sellers)
             THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN oi.seller_id NOT IN (SELECT seller_id FROM top_bad_sellers)
                      THEN 1 ELSE 0 END), 0) AS simulated_negative_rate,
    COUNT(*) AS total_reviews,
    SUM(CASE WHEN oi.seller_id IN (SELECT seller_id FROM top_bad_sellers)
             THEN 1 ELSE 0 END) AS removed_reviews
FROM order_reviews r
JOIN order_items oi ON r.order_id = oi.order_id
"""


class WhatIfOutput(BaseModel):
    scenario: str
    top_n: int
    min_reviews_filter: int
    current_avg_score: float
    simulated_avg_score: float
    estimated_score_improvement: float
    current_negative_rate: float
    simulated_negative_rate: float
    estimated_negative_rate_drop: float
    total_reviews: int
    removed_reviews: int
    assumptions: list[str] = Field(default_factory=list)
    summary: str


def _f(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def run_what_if(top_n: int = 20, min_reviews: int = 20) -> dict[str, Any]:
    rows = db.query(_WHAT_IF_SQL, (int(min_reviews), int(top_n)))
    if not rows:
        return WhatIfOutput(
            scenario=f"Delist Top {top_n} high-negative-review sellers",
            top_n=int(top_n),
            min_reviews_filter=int(min_reviews),
            current_avg_score=0.0,
            simulated_avg_score=0.0,
            estimated_score_improvement=0.0,
            current_negative_rate=0.0,
            simulated_negative_rate=0.0,
            estimated_negative_rate_drop=0.0,
            total_reviews=0,
            removed_reviews=0,
            summary="无可用评论数据，无法运行 What-if 模拟。",
        ).model_dump()

    r = rows[0]
    cur = _f(r.get("current_avg_score"))
    sim = _f(r.get("simulated_avg_score"))
    cur_neg = _f(r.get("current_negative_rate"))
    sim_neg = _f(r.get("simulated_negative_rate"))
    total = int(r.get("total_reviews") or 0)
    removed = int(r.get("removed_reviews") or 0)

    summary = (
        f"假设下架差评率最高的 Top {top_n} 卖家（要求样本量≥{min_reviews}）"
        f"将剔除 {removed}/{total} 条评论："
        f"平台平均评分由 {cur:.3f} 提升至 {sim:.3f}（+{sim - cur:.3f}），"
        f"差评率由 {cur_neg:.2%} 降至 {sim_neg:.2%}（-{cur_neg - sim_neg:.2%}）。"
    )

    return WhatIfOutput(
        scenario=f"Delist Top {top_n} high-negative-review sellers",
        top_n=int(top_n),
        min_reviews_filter=int(min_reviews),
        current_avg_score=cur,
        simulated_avg_score=sim,
        estimated_score_improvement=sim - cur,
        current_negative_rate=cur_neg,
        simulated_negative_rate=sim_neg,
        estimated_negative_rate_drop=cur_neg - sim_neg,
        total_reviews=total,
        removed_reviews=removed,
        assumptions=[
            "为静态反事实估计：仅从样本中剔除被下架卖家的订单评论，不重新分配需求",
            "未考虑用户在替代卖家上的购买体验差异（替代效应可能拉低或拉高估计）",
            "差评率阈值使用 review_score<=2，与本项目其他分析保持一致",
            f"卖家筛选要求评论数 >= {min_reviews} 以避免小样本噪声",
        ],
        summary=summary,
    ).model_dump()


def build_what_if_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=run_what_if,
        name="what_if_tool",
        description=(
            "What-if：模拟下架差评率最高的 Top N 卖家后，平台平均评分与差评率的变化。"
            "为静态反事实估计，结果中包含明确的假设说明。"
        ),
    )


if __name__ == "__main__":
    import json
    print(json.dumps(run_what_if(), ensure_ascii=False, indent=2))
