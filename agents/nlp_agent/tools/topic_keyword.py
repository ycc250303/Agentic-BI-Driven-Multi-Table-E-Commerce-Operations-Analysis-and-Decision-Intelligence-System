"""
P0 基线：葡萄牙语关键词主题分类。

输入：
- 取 `order_reviews` 中 `review_score <= 2` 的差评样本（JOIN orders / order_items /
  products / sellers / customers / product_category_name_translation）

输出（dict 形式，与 `state["review_insights"]` 契约一致）：
- `topic_distribution`：每个主题的差评数
- `top_categories / top_seller_states / top_customer_states`：受影响 Top 5
- `method = "keyword_pt_baseline"`
- `summary`：自然语言摘要

关键词词典优先从 `config/nlp_agent/topic_keywords.yaml` 加载；
若文件缺失或解析失败，回退到内置默认词典，保证 Agent 在配置异常时仍可启动。
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agents.nlp_agent import db


# ---------------------------------------------------------------------------
# SQL：差评抽样（与 review_insight 旧实现保持完全一致，避免行为漂移）
# ---------------------------------------------------------------------------

_NEG_REVIEW_SQL = """
SELECT
    r.review_score,
    r.review_comment_message,
    COALESCE(pct.product_category_name_english,
             p.product_category_name) AS category,
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


# ---------------------------------------------------------------------------
# 内置默认词典：YAML 不可用时的兜底
# ---------------------------------------------------------------------------

_DEFAULT_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "delivery_delay": ["atraso", "atrasado", "atrasada", "demora", "demorou", "tarde"],
    "not_received": [
        "nao recebi", "não recebi", "nao chegou", "não chegou", "nunca chegou",
        "nao entregue", "não entregue",
    ],
    "product_quality": [
        "defeito", "defeituoso", "quebrado", "quebrada", "qualidade",
        "ruim", "péssimo", "pessimo",
    ],
    "wrong_item": ["errado", "errada", "diferente", "trocado", "troca"],
    "customer_service": [
        "atendimento", "suporte", "resposta", "vendedor não", "vendedor nao",
    ],
    "price_freight": ["frete", "caro", "preço", "preco", "cobrança", "cobranca"],
    "missing_parts": ["faltando", "incompleto", "incompleta"],
}


# ---------------------------------------------------------------------------
# 词典加载：优先 PyYAML；缺失时用极简内置解析；都失败时回退默认词典
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """从当前文件向上找含 `config/nlp_agent` 的项目根。"""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config" / "nlp_agent").exists():
            return parent
    raise RuntimeError("未找到项目根目录下的 config/nlp_agent 目录。")


def _parse_simple_yaml(text: str) -> dict[str, list[str]]:
    """极简 YAML 解析器：只支持 topic_keywords.yaml 这种结构。

    支持：
        topics:
          - name: <topic_name>
            keywords:
              - <kw>
              - "<kw with quotes>"

    其它语法（嵌套 dict、锚点、多文档等）一律不支持，调用者请保持文件简单。
    """
    topics: dict[str, list[str]] = {}
    current_name: str | None = None
    current_kws: list[str] | None = None
    in_keywords = False

    def _strip_quotes(s: str) -> str:
        s = s.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            return s[1:-1]
        return s

    for raw_line in text.splitlines():
        # 移除尾部行内注释（# 之前如果是引号包裹的不去；本文件场景下安全）
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if indent == 0 and stripped == "topics:":
            continue

        # 主题块开头："  - name: xxx"
        if stripped.startswith("- name:"):
            # 收尾上一个主题
            if current_name is not None and current_kws is not None:
                topics[current_name] = current_kws
            current_name = _strip_quotes(stripped[len("- name:"):].strip())
            current_kws = []
            in_keywords = False
            continue

        # "    keywords:"
        if stripped == "keywords:":
            in_keywords = True
            continue

        # 关键词列表行："      - xxx"
        if in_keywords and stripped.startswith("-"):
            kw = _strip_quotes(stripped[1:].strip())
            if kw and current_kws is not None:
                current_kws.append(kw)
            continue

    # 收尾最后一个主题
    if current_name is not None and current_kws is not None:
        topics[current_name] = current_kws

    return topics


@lru_cache(maxsize=1)
def _load_topic_keywords() -> dict[str, list[str]]:
    """加载葡语主题关键词词典。失败时回退到内置默认词典。"""
    try:
        yaml_path = _project_root() / "config" / "nlp_agent" / "topic_keywords.yaml"
        if not yaml_path.exists():
            return dict(_DEFAULT_TOPIC_KEYWORDS)

        text = yaml_path.read_text(encoding="utf-8")
        # 优先尝试 PyYAML，可选依赖
        try:
            import yaml  # type: ignore  # noqa: WPS433

            data = yaml.safe_load(text) or {}
            topics_list = data.get("topics") or []
            parsed = {
                str(t["name"]): [str(k) for k in (t.get("keywords") or [])]
                for t in topics_list
                if isinstance(t, dict) and t.get("name")
            }
        except Exception:
            parsed = _parse_simple_yaml(text)

        # 过滤掉空主题，避免脏配置
        parsed = {k: v for k, v in parsed.items() if v}
        return parsed or dict(_DEFAULT_TOPIC_KEYWORDS)
    except Exception:
        return dict(_DEFAULT_TOPIC_KEYWORDS)


# ---------------------------------------------------------------------------
# 分类与统计
# ---------------------------------------------------------------------------


class ReviewInsightOutput(BaseModel):
    """`state["review_insights"]` 的 P0 基线 schema。"""

    sample_size: int
    negative_review_count: int
    topic_distribution: dict[str, int]
    top_categories: list[dict[str, Any]] = Field(default_factory=list)
    top_seller_states: list[dict[str, Any]] = Field(default_factory=list)
    top_customer_states: list[dict[str, Any]] = Field(default_factory=list)
    complaints_by_category: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Top 差评品类的主题原因交叉表：每条形如 "
            "{category, total, dominant_topic, dominant_share, topic_distribution: {...}}"
        ),
    )
    method: str
    summary: str


def _classify_topic(text: str, topic_keywords: dict[str, list[str]] | None = None) -> str:
    """对单条评论做"先到先得"的关键词归类。

    `topic_keywords` 默认从 YAML 加载（带 lru_cache）；测试时可注入自定义词典。
    """
    t = (text or "").lower()
    if not t.strip():
        return "empty_text"
    kw_dict = topic_keywords if topic_keywords is not None else _load_topic_keywords()
    for topic, words in kw_dict.items():
        if any(w in t for w in words):
            return topic
    return "other"


def _top_n(counter: Counter, n: int = 5) -> list[dict[str, Any]]:
    return [{"key": k, "count": v} for k, v in counter.most_common(n) if k]


def _summarize_category_complaints(
    cat_topic_grid: dict[str, Counter],
    top_n_categories: int = 10,
    min_sample: int = 5,
) -> list[dict[str, Any]]:
    """把 {category: {topic: cnt}} 嵌套字典折叠成 Top N 品类 × 主题分布列表。

    每个元素：
        {
          "category": "bed_bath_table",
          "total": 90,
          "dominant_topic": "delivery_delay",
          "dominant_share": 0.42,
          "topic_distribution": {"delivery_delay": 38, "product_quality": 22, ...}
        }
    """
    rows: list[tuple[int, dict[str, Any]]] = []
    for cat, topics in cat_topic_grid.items():
        total = sum(topics.values())
        if total < min_sample:
            continue
        dom_topic, dom_cnt = topics.most_common(1)[0]
        rows.append((total, {
            "category": cat,
            "total": total,
            "dominant_topic": dom_topic,
            "dominant_share": round(dom_cnt / total, 4),
            "topic_distribution": dict(topics),
        }))
    # 按品类总差评量降序，取 Top N
    rows.sort(key=lambda x: -x[0])
    return [item for _, item in rows[:top_n_categories]]


def run_review_insight(sample_size: int = 1000) -> dict[str, Any]:
    """对差评样本做关键词主题分类，输出结构化洞察 dict。"""
    rows = db.query(_NEG_REVIEW_SQL, (int(sample_size),))
    if not rows:
        return ReviewInsightOutput(
            sample_size=int(sample_size),
            negative_review_count=0,
            topic_distribution={},
            method="keyword_pt_baseline",
            summary="数据库中未取到 review_score <= 2 的差评样本，无法生成评论洞察。",
        ).model_dump()

    kw_dict = _load_topic_keywords()
    topic_counter: Counter = Counter()
    cat_counter: Counter = Counter()
    seller_state_counter: Counter = Counter()
    cust_state_counter: Counter = Counter()
    # 嵌套：{category -> Counter({topic -> cnt})}
    cat_topic_grid: dict[str, Counter] = {}

    for r in rows:
        topic = _classify_topic(str(r.get("review_comment_message") or ""), kw_dict)
        topic_counter[topic] += 1

        category = r.get("category")
        if category:
            cat_str = str(category)
            cat_counter[cat_str] += 1
            cat_topic_grid.setdefault(cat_str, Counter())[topic] += 1
        if r.get("seller_state"):
            seller_state_counter[str(r["seller_state"])] += 1
        if r.get("customer_state"):
            cust_state_counter[str(r["customer_state"])] += 1

    complaints_by_category = _summarize_category_complaints(
        cat_topic_grid, top_n_categories=10, min_sample=5,
    )

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
        complaints_by_category=complaints_by_category,
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
