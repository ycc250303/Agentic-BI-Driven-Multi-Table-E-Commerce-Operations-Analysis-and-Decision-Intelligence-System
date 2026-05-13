"""
Review Insight 工具：抽取近期低分（review_score <= 2）评论，按葡萄牙语关键词做主题分类，
输出主题计数、Top 受影响品类 / 卖家州 / 客户州。属于轻量 NLP，便于后续替换为情感分析模型。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agents.decision_agent import db


_NEG_REVIEW_SQL = """
SELECT
    r.review_score,
    r.review_comment_message,
    pct.product_category_name_english AS category_en,
    s.seller_state,
    c.customer_state
FROM order_reviews r
JOIN orders o ON r.order_id = o.order_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_name_translation pct
    ON p.product_category_name = pct.product_category_name
JOIN sellers s ON oi.seller_id = s.seller_id
JOIN customers c ON o.customer_id = c.customer_id
WHERE r.review_score <= 2
LIMIT %s
"""


# 葡萄牙语关键词；命中第一条匹配的主题为该评论主题（先到先得，避免重复计数）
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "delivery_delay": ["atraso", "atrasado", "atrasada", "demora", "demorou", "tarde"],
    "not_received": [
        "nao recebi", "não recebi", "nao chegou", "não chegou", "nunca chegou",
        "nao entregue", "não entregue",
    ],
    "product_quality": ["defeito", "defeituoso", "quebrado", "quebrada", "qualidade", "ruim", "péssimo", "pessimo"],
    "wrong_item": ["errado", "errada", "diferente", "trocado", "troca"],
    "customer_service": ["atendimento", "suporte", "resposta", "vendedor não", "vendedor nao"],
    "price_freight": ["frete", "caro", "preço", "preco", "cobrança", "cobranca"],
    "missing_parts": ["faltando", "incompleto", "incompleta"],
}


class ReviewInsightOutput(BaseModel):
    sample_size: int
    negative_review_count: int
    topic_distribution: dict[str, int]
    top_categories: list[dict[str, Any]] = Field(default_factory=list)
    top_seller_states: list[dict[str, Any]] = Field(default_factory=list)
    top_customer_states: list[dict[str, Any]] = Field(default_factory=list)
    method: str
    summary: str


def _classify_topic(text: str) -> str:
    t = (text or "").lower()
    if not t.strip():
        return "empty_text"
    for topic, words in _TOPIC_KEYWORDS.items():
        if any(w in t for w in words):
            return topic
    return "other"


def _top_n(counter: Counter, n: int = 5) -> list[dict[str, Any]]:
    return [{"key": k, "count": v} for k, v in counter.most_common(n) if k]


def run_review_insight(sample_size: int = 1000) -> dict[str, Any]:
    rows = db.query(_NEG_REVIEW_SQL, (int(sample_size),))
    if not rows:
        return ReviewInsightOutput(
            sample_size=int(sample_size),
            negative_review_count=0,
            topic_distribution={},
            method="keyword_pt_baseline",
            summary="数据库中未取到 review_score <= 2 的差评样本，无法生成评论洞察。",
        ).model_dump()

    topic_counter: Counter = Counter()
    cat_counter: Counter = Counter()
    seller_state_counter: Counter = Counter()
    cust_state_counter: Counter = Counter()

    for r in rows:
        topic = _classify_topic(str(r.get("review_comment_message") or ""))
        topic_counter[topic] += 1
        if r.get("category_en"):
            cat_counter[str(r["category_en"])] += 1
        if r.get("seller_state"):
            seller_state_counter[str(r["seller_state"])] += 1
        if r.get("customer_state"):
            cust_state_counter[str(r["customer_state"])] += 1

    total = sum(topic_counter.values())
    top1, top1_cnt = topic_counter.most_common(1)[0] if topic_counter else ("", 0)
    summary = (
        f"采样 {len(rows)} 条 review_score<=2 的差评（葡语关键词主题分类基线）。"
        f"主导主题为「{top1}」，占比 {top1_cnt / total:.1%}。"
        if total
        else "差评样本主题分布为空。"
    )

    return ReviewInsightOutput(
        sample_size=int(sample_size),
        negative_review_count=len(rows),
        topic_distribution=dict(topic_counter),
        top_categories=_top_n(cat_counter, 5),
        top_seller_states=_top_n(seller_state_counter, 5),
        top_customer_states=_top_n(cust_state_counter, 5),
        method="keyword_pt_baseline",
        summary=summary,
    ).model_dump()


def build_review_insight_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=run_review_insight,
        name="review_insight_tool",
        description=(
            "对 order_reviews 中 review_score<=2 的差评进行采样，使用葡萄牙语关键词做主题分类，"
            "输出主题分布、受影响 Top 品类 / 卖家州 / 客户州。"
        ),
    )


if __name__ == "__main__":
    import json
    print(json.dumps(run_review_insight(200), ensure_ascii=False, indent=2))
