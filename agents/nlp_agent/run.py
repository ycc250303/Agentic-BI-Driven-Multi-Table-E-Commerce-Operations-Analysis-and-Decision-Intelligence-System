"""
NLP / 评论洞察 Agent 入口。

对外暴露：
- `ReviewInsightAgent`：可独立 `run(state)` 的类，便于离线 / 单测 / 注入自定义工具。
- `nlp_node(state)`：LangGraph node 函数，签名 state -> state，供 Orchestrator
  在 `intent ∈ {diagnostic, prescriptive}` 路径上挂接。
- `should_run_nlp(question, intent)`：路由判定，给 Orchestrator 决策是否需要 NLP 节点。

一次 `run(state)` 内部串行调用三类子工具：
1. `topic_fn`（默认 `topic_keyword.run_review_insight`）：差评关键词主题分类，
   含主题 × Top 品类交叉表 `complaints_by_category`
2. `sentiment_fn`（默认 `sentiment.aggregate_sentiment`）：从 `review_sentiment`
   表读极性 / 综合分数聚合（不调模型，毫秒级），含按品类 / 客户州 / 卖家州下钻
3. `wordcloud_fn`（默认 `wordcloud_data.run_wordcloud_data`）：好评 / 差评对比
   词云数据，给 viz_agent 渲染对比词云使用

三者结果合并成单一 `state["review_insights"]` 字典，下游 Decision Agent 直接消费。
任何子工具失败都不会阻塞整体流程（降级写入提示信息）。

CLI 用法：
    python -m agents.nlp_agent.run --sample 500
    python -m agents.nlp_agent.run --question "Top 10 差评品类的主要原因？" --intent diagnostic
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from agents.nlp_agent.tools.sentiment import aggregate_sentiment
from agents.nlp_agent.tools.topic_keyword import run_review_insight
from agents.nlp_agent.tools.topic_model import aggregate_bertopic
from agents.nlp_agent.tools.wordcloud_data import run_wordcloud_data


# ---------------------------------------------------------------------------
# 路由：Orchestrator 用来决定是否触发 NLP 节点
# ---------------------------------------------------------------------------

_REVIEW_KEYWORDS = (
    "评论", "差评", "评分", "抱怨", "原因", "满意度", "口碑", "投诉",
    "review", "negative", "complaint", "sentiment", "feedback",
)
_PRESCRIPTIVE_INTENTS = ("diagnostic", "prescriptive")


def _has_kw(text: str, keywords: tuple[str, ...]) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords)


def should_run_nlp(question: str = "", intent: str = "") -> bool:
    """Orchestrator 路由判定：是否需要调度 NLP Agent。

    触发条件（任一）：
    - intent 为 `diagnostic` / `prescriptive`（往往需要差评原因诊断）
    - 用户问题命中评论 / 差评 / 情感等关键词
    """
    if intent in _PRESCRIPTIVE_INTENTS:
        return True
    return _has_kw(question, _REVIEW_KEYWORDS)


# ---------------------------------------------------------------------------
# Agent 主类
# ---------------------------------------------------------------------------


class ReviewInsightAgent:
    """NLP / 评论洞察 Agent。

    一次 `run` 内部串行调用：
    - `topic_fn`：差评关键词主题分类（含主题 × 品类交叉表）
    - `sentiment_fn`：情感聚合（按品类 / 客户州 / 卖家州下钻）
    - `wordcloud_fn`：好评 / 差评对比词云数据

    所有子工具均可注入自定义实现，便于单测 / 离线运行。
    任何子工具失败都不会阻塞整体流程：失败时写入降级 summary，主流程继续。
    """

    def __init__(
        self,
        topic_fn: Callable[..., dict[str, Any]] = run_review_insight,
        sentiment_fn: Callable[..., dict[str, Any]] | None = aggregate_sentiment,
        wordcloud_fn: Callable[..., dict[str, Any]] | None = run_wordcloud_data,
        bertopic_fn: Callable[..., dict[str, Any]] | None = aggregate_bertopic,
        sample_size: int = 1000,
        wordcloud_top_n: int = 80,
        wordcloud_sample: int = 4000,
    ):
        self._topic_fn = topic_fn
        self._sentiment_fn = sentiment_fn
        self._wordcloud_fn = wordcloud_fn
        self._bertopic_fn = bertopic_fn
        self._sample_size = int(sample_size)
        self._wc_top_n = int(wordcloud_top_n)
        self._wc_sample = int(wordcloud_sample)

    # ----- helpers -----
    def _has_bertopic_data(self) -> bool:
        """快速探测 review_topic_meta 表是否有数据，避免无效回退。"""
        if self._bertopic_fn is None:
            return False
        try:
            bt = self._bertopic_fn()
            return bool(bt and bt.get("topics"))
        except Exception:
            return False

    def _build_insight(self) -> dict[str, Any]:
        """组合 BERTopic + sentiment + wordcloud + (回退) 关键词分类。

        优先走 BERTopic 无监督主题（无 other 盲区，粒度更细）；仅在 BERTopic
        表为空时才回退到关键词分类作为兜底。
        """
        use_bertopic = self._has_bertopic_data()

        # BERTopic 优先：跳过昂贵的差评抽样 JOIN，直接用 topic meta 聚合
        if use_bertopic:
            bt = self._bertopic_fn()  # type: ignore[misc]
            insight: dict[str, Any] = {
                "sample_size": self._sample_size,
                "negative_review_count": 0,
                "topic_distribution": {},
                "top_categories": [],
                "top_seller_states": [],
                "top_customer_states": [],
                "complaints_by_category": bt.get("complaints_by_category") or [],
                "method": bt.get("method") or "bertopic",
                "summary": bt.get("summary") or "",
                "topics_bertopic": bt,
            }
        else:
            # 回退：关键词分类（P0 基线）
            insight = self._topic_fn(self._sample_size)

        # 情感聚合（软依赖）
        if self._sentiment_fn is not None:
            try:
                sentiment = self._sentiment_fn()
                if sentiment and sentiment.get("total"):
                    insight["sentiment"] = sentiment
            except Exception as e:  # noqa: BLE001
                insight["sentiment"] = {"method": "n/a",
                                        "summary": f"sentiment 聚合失败：{e}"}

        # 词云数据（软依赖）
        if self._wordcloud_fn is not None:
            try:
                wc = self._wordcloud_fn(
                    top_n=self._wc_top_n,
                    pos_sample=self._wc_sample,
                    neg_sample=self._wc_sample,
                )
                if wc and (wc.get("positive") or wc.get("negative")):
                    insight["wordcloud"] = wc
            except Exception as e:  # noqa: BLE001
                insight["wordcloud"] = {"method": "n/a",
                                        "summary": f"wordcloud 数据生成失败：{e}"}

        return insight

    # ----- main -----
    def run(
        self,
        state: dict[str, Any] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        """执行评论洞察并写回 `state["review_insights"]`。

        - state 为 None 时返回不带 state 的洞察 dict（CLI / 单测使用）。
        - state["review_insights"] 已存在时按幂等跳过，避免覆盖上游结果。
        - on_tool_end(tool_name, payload_str) 用于在 Web 端实时推送（与 sql_agent 风格一致）。
        """
        def _emit(tool: str, payload: Any) -> None:
            if on_tool_end is None:
                return
            on_tool_end(
                tool,
                payload if isinstance(payload, str)
                else json.dumps(payload, ensure_ascii=False, indent=2),
            )

        # 无 state 模式：纯工具调用，直接返回洞察 dict
        if state is None:
            insight = self._build_insight()
            _emit("review_insight_tool", insight)
            return insight

        # 幂等：上游已写入则不重复执行
        if "review_insights" in state and state.get("review_insights"):
            _emit("review_insight_tool", state["review_insights"])
            return state

        try:
            state["review_insights"] = self._build_insight()
        except Exception as e:  # 失败兜底：写入降级 summary，避免阻塞主流程
            state["review_insights"] = {
                "method": "n/a",
                "summary": f"NLP Agent 评论洞察执行失败：{e}",
            }
        _emit("review_insight_tool", state["review_insights"])
        return state


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


def nlp_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node：使用默认工具构造 Agent，写回更新后的 state。

    Orchestrator 接入示例：
        workflow.add_node("nlp", nlp_node)
        workflow.add_conditional_edges(
            "data_analysis",
            lambda s: "nlp" if should_run_nlp(s.get("question",""), s.get("intent","")) else "decision",
            {"nlp": "nlp", "decision": "decision"},
        )
        workflow.add_edge("nlp", "decision")
    """
    return ReviewInsightAgent().run(state)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="NLP / 评论洞察 Agent CLI")
    p.add_argument("--sample", type=int, default=200, help="差评抽样上限（默认 200）")
    p.add_argument("--question", type=str, default="", help="模拟用户问题，用于路由演示")
    p.add_argument("--intent", type=str, default="", help="Orchestrator 解析的 intent")
    p.add_argument(
        "--no-state",
        action="store_true",
        help="忽略 state，直接调用工具并打印洞察 JSON（适合单跑工具调试）",
    )
    return p


def main() -> None:
    args = _build_argparser().parse_args()

    if args.no_state or (not args.question and not args.intent):
        # 模式 A：直接跑工具
        agent = ReviewInsightAgent(sample_size=args.sample)
        result = agent.run(state=None, on_tool_end=lambda t, p: None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 模式 B：模拟 LangGraph state 流转
    if not should_run_nlp(args.question, args.intent):
        print(
            json.dumps(
                {
                    "skipped": True,
                    "reason": "should_run_nlp 判定不需要触发 NLP Agent",
                    "question": args.question,
                    "intent": args.intent,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    state: dict[str, Any] = {"question": args.question, "intent": args.intent}
    agent = ReviewInsightAgent(sample_size=args.sample)
    state = agent.run(
        state=state,
        on_tool_end=lambda t, p: print(f"\n=== {t} ===\n{p[:1200]}"),
    )
    print("\n===== final state =====")
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
