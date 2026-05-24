"""
NLP / 评论洞察 Agent 的 State 类型定义。

字段命名与 `agents.decision_agent.state.AgentState` 对齐，可直接合入全局 LangGraph
共享状态（StateGraph 用 TypedDict 是结构化合并，多余字段不会冲突）。

NLP Agent 主要：
- 读取：`question` / `intent`
- 写入：`review_insights`
"""

from __future__ import annotations

from typing import Any, TypedDict


class ReviewInsightsPayload(TypedDict, total=False):
    """`state["review_insights"]` 的内部结构（决策 Agent 直接消费此字段）。

    覆盖：
    - 关键词主题分类基线（topic_distribution / top_categories / top_seller_states /
      top_customer_states / complaints_by_category）
    - 情感分析聚合（sentiment：极性分布 + 按品类 / 按州下钻）
    - 词云对比数据（wordcloud：好评 / 差评高频词）
    - 后续 BERTopic 主题建模（topics_bertopic，预留）
    """

    # ---- 关键词主题分类（topic_keyword.py）----
    sample_size: int
    negative_review_count: int
    topic_distribution: dict[str, int]
    top_categories: list[dict[str, Any]]
    top_seller_states: list[dict[str, Any]]
    top_customer_states: list[dict[str, Any]]
    complaints_by_category: list[dict[str, Any]]
    method: str
    summary: str

    # ---- 情感分析（sentiment.py，读 review_sentiment 表）----
    sentiment: dict[str, Any]

    # ---- 好评 / 差评对比词云（wordcloud_data.py）----
    wordcloud: dict[str, Any]

    # ---- BERTopic 无监督主题（topic_model.py，读 review_topics 表）----
    topics_bertopic: dict[str, Any]


class ReviewInsightState(TypedDict, total=False):
    """NLP Agent 关心的最小子集 State；与全局 `AgentState` 兼容。"""

    # 输入
    question: str
    intent: str  # descriptive / diagnostic / predictive / what_if / prescriptive

    # 输出
    review_insights: ReviewInsightsPayload
