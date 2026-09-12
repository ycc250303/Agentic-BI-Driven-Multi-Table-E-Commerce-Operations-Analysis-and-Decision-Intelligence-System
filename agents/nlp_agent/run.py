"""
NLP / 评论洞察 Agent 入口。

对外暴露：
- `ReviewInsightAgent`：可独立 `run()` 的类，返回洞察 dict（不写全局 state）。
- `should_run_nlp(question, intent)`：路由判定，给协调器决定是否调度 NLP 节点。

一次 `run()` 内部串行调用：
1. BERTopic 聚合（表空则回退关键词主题分类）
2. `sentiment.aggregate_sentiment`：读 `review_sentiment` 毫秒级聚合
3. `wordcloud_data.run_wordcloud_data`：好评 / 差评对比词云

协调器负责把返回值写入 `review_insights` / `nlp_result`。
任何子工具失败都不会阻塞整体流程（降级写入提示信息）。

CLI 用法：
    python -m agents.nlp_agent.run --sample 500
    python -m agents.nlp_agent.run --question "Top 10 差评品类的主要原因？" --intent diagnostic
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from typing import Any

from agents.nlp_agent.tools.sentiment import aggregate_sentiment
from agents.nlp_agent.tools.topic_keyword import run_review_insight
from agents.nlp_agent.tools.topic_model import aggregate_bertopic
from agents.nlp_agent.tools.wordcloud_data import run_wordcloud_data

logger = logging.getLogger(__name__)


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
    # 诊断/处方默认走评论洞察；预测仅在问句本身像「评论/满意度」时才触发
    if intent in _PRESCRIPTIVE_INTENTS:
        return True
    if intent == "predictive" and _has_kw(question, _REVIEW_KEYWORDS):
        return True
    return _has_kw(question, _REVIEW_KEYWORDS)


# ---------------------------------------------------------------------------
# Agent 主类
# ---------------------------------------------------------------------------


class ReviewInsightAgent:
    """NLP / 评论洞察 Agent。

    一次 `run` 返回洞察 dict，不改写协调器 state。
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

    def _has_bertopic_data(self) -> bool:
        """快速探测 review_topic_meta 表是否有数据，避免无效回退。"""
        if self._bertopic_fn is None:
            return False
        try:
            bt = self._bertopic_fn()
            return bool(bt and bt.get("topics"))
        except Exception:
            logger.warning("探测 BERTopic 表失败，回退关键词主题。", exc_info=True)
            return False

    def _build_insight(self) -> dict[str, Any]:
        """组合 BERTopic + sentiment + wordcloud + (回退) 关键词分类。

        优先走 BERTopic 无监督主题（无 other 盲区，粒度更细）；仅在 BERTopic
        表为空时才回退到关键词分类作为兜底。
        """
        # 在线路径不调 LLM、不跑重模型：主题/情感只读离线表；关键词/词云才碰原始评论
        use_bertopic = self._has_bertopic_data()

        # ① 主题：BERTopic 优先（读 review_topics），表空才回退关键词抽样 JOIN
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
            # 回退：关键词分类（P0 基线，实时抽 order_reviews）
            insight = self._topic_fn(self._sample_size)

        # ② 情感：只聚合 review_sentiment；表空/失败写占位，不阻塞后面
        if self._sentiment_fn is not None:
            try:
                sentiment = self._sentiment_fn()
                if sentiment and sentiment.get("total"):
                    insight["sentiment"] = sentiment
            except Exception as e:  # noqa: BLE001
                logger.warning("sentiment 聚合失败：%s", e)
                insight["sentiment"] = {"method": "n/a",
                                        "summary": f"sentiment 聚合失败：{e}"}

        # ③ 词云：好评/差评两路词频，给可视化 Agent 渲染对比词云
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
                logger.warning("wordcloud 数据生成失败：%s", e)
                insight["wordcloud"] = {"method": "n/a",
                                        "summary": f"wordcloud 数据生成失败：{e}"}

        return insight

    def run(
        self,
        on_tool_end: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        """执行评论洞察，返回洞察 dict（不写协调器 state）。"""
        try:
            insight = self._build_insight()
        except Exception as e:  # 失败兜底：写入降级 summary，避免阻塞主流程
            logger.warning("NLP Agent 评论洞察执行失败：%s", e)
            insight = {
                "method": "n/a",
                "summary": f"NLP Agent 评论洞察执行失败：{e}",
            }
        if on_tool_end is not None:
            on_tool_end(
                "review_insight_tool",
                json.dumps(insight, ensure_ascii=False, indent=2),
            )
        return insight


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
        help="忽略路由判定，直接调用工具并打印洞察 JSON",
    )
    return p


def main() -> None:
    from agents.common.logging import configure_logging

    configure_logging()
    args = _build_argparser().parse_args()

    if args.no_state or (not args.question and not args.intent):
        agent = ReviewInsightAgent(sample_size=args.sample)
        result = agent.run()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

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

    insights = ReviewInsightAgent(sample_size=args.sample).run(
        on_tool_end=lambda t, p: print(f"\n=== {t} ===\n{p[:1200]}"),
    )
    print("\n===== review_insights =====")
    print(json.dumps(
        {
            "question": args.question,
            "intent": args.intent,
            "review_insights": insights,
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
