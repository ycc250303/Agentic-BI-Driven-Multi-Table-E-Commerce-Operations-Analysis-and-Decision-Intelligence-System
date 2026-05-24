"""
NLP Agent 完整能力演示脚本。

展示当前 NLP Agent 能产出的全部 review_insights 字段，便于人眼验证模型与聚合质量。

包含：
1. 单条评论的真实情感预测样本（看模型靠不靠谱）
2. 整体极性分布
3. review_score × polarity 交叉表（看模型与人工评分一致性）
4. 按品类的负面情感排行
5. 按客户州 / 卖家州的情感排行
6. 主题 × 品类交叉表（差评原因下钻）
7. 好评 / 差评高频词对比
8. NLP Agent 完整流程一次跑通

用法：
    .venv/bin/python tasks/nlp_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from agents.nlp_agent import db
from agents.nlp_agent.run import ReviewInsightAgent, should_run_nlp


# ═══════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════

def hr(title: str = "", char: str = "═"):
    if title:
        print(f"\n{char * 5} {title} {char * (75 - len(title))}")
    else:
        print(char * 80)


def fmt_score(score: float) -> str:
    if score >= 0.5:
        return f"+{score:.3f} 🟢 强正"
    if score >= 0.1:
        return f"+{score:.3f} 🟢 正"
    if score > -0.1:
        return f"{score:+.3f} ⚪ 中性"
    if score > -0.5:
        return f"{score:.3f} 🔴 负"
    return f"{score:.3f} 🔴 强负"


def bar(value: int, total: int, width: int = 30, fill: str = "█") -> str:
    pct = value / max(total, 1)
    n = int(round(pct * width))
    return fill * n + "·" * (width - n) + f" {pct:6.1%}"


# ═══════════════════════════════════════════════════════════════════════════
# 1. 单条预测
# ═══════════════════════════════════════════════════════════════════════════

def show_single_predictions():
    hr("【1】抽 6 条评论看模型对单条文本的预测")
    rows = db.query("""
        SELECT r.review_id, r.review_score, r.review_comment_message,
               s.polarity, s.polarity_score, s.pos_prob, s.neu_prob, s.neg_prob
        FROM order_reviews r
        JOIN review_sentiment s ON s.review_id = r.review_id
        WHERE r.review_comment_message IS NOT NULL
          AND CHAR_LENGTH(r.review_comment_message) BETWEEN 30 AND 200
        ORDER BY RAND()
        LIMIT 6
    """)
    for i, r in enumerate(rows, 1):
        msg = (r["review_comment_message"] or "").strip().replace("\n", " ")
        if len(msg) > 150:
            msg = msg[:147] + "…"
        print(f"\n[{i}] review_score={r['review_score']}  评论：{msg}")
        print(f"    模型预测：{r['polarity']:3s}  "
              f"score={fmt_score(float(r['polarity_score']))}  "
              f"P(POS)={float(r['pos_prob']):.0%} "
              f"P(NEU)={float(r['neu_prob']):.0%} "
              f"P(NEG)={float(r['neg_prob']):.0%}")


# ═══════════════════════════════════════════════════════════════════════════
# 2~5：从 sentiment 聚合直接展示
# ═══════════════════════════════════════════════════════════════════════════

def show_sentiment_aggregations(s: dict):
    hr("【2】整体极性分布（review_sentiment 全表）")
    pd = s["polarity_distribution"]
    total = s["total"]
    for k in ("POS", "NEU", "NEG"):
        c = pd.get(k, 0)
        print(f"  {k:5s} {c:>8,d}   {bar(c, total)}")
    print(f"  TOTAL {total:>8,d}    加权平均极性: {fmt_score(s['avg_polarity_score'])}")

    hr("【3】review_score × polarity 交叉表（人工评分 × 模型预测）")
    grid: dict[int, dict[str, int]] = {}
    for r in s["by_review_score"]:
        grid.setdefault(int(r["review_score"]), {})[r["polarity"]] = int(r["count"])
    print(f"  {'score':>6s} | {'POS':>9s} {'NEU':>9s} {'NEG':>9s} | "
          f"{'POS%':>6s} {'NEU%':>6s} {'NEG%':>6s} | 主导  一致性")
    print(f"  {'-'*6}-+-{'-'*9} {'-'*9} {'-'*9}-+-{'-'*6} {'-'*6} {'-'*6}-+-{'-'*8}")
    for score in sorted(grid.keys()):
        row = grid[score]
        p, n, ng = row.get("POS", 0), row.get("NEU", 0), row.get("NEG", 0)
        tot = p + n + ng
        if tot == 0:
            continue
        dom = max(("POS", "NEU", "NEG"), key=lambda k: row.get(k, 0))
        if score in (1, 2):
            ok = "✅" if dom == "NEG" else "⚠️"
        elif score in (4, 5):
            ok = "✅" if dom == "POS" else "⚠️"
        else:
            ok = "—"
        print(f"  {score:>6d} | {p:>9,d} {n:>9,d} {ng:>9,d} | "
              f"{p/tot:>5.1%} {n/tot:>5.1%} {ng/tot:>5.1%} | {dom:<5s} {ok}")

    hr("【4】最负面品类排行（基于情感分数）")
    wc = s.get("worst_categories", [])
    if not wc:
        print("  无满足样本量的品类。")
    else:
        print(f"  {'品类':<35s} {'avg_score':>20s}  neg_rate  sample")
        print(f"  {'-'*35} {'-'*20}  --------  ------")
        for c in wc[:10]:
            cat = (c["category"] or "(unknown)")[:35]
            print(f"  {cat:<35s} {fmt_score(c['avg_score']):>20s}  "
                  f"{c['neg_rate']:>7.1%}  {c['sample']:>6,d}")

    hr("【5】最负面客户州 Top 5")
    cs = s.get("by_customer_state") or []
    print(f"  {'state':<6s} {'avg_score':>20s}  neg_rate  sample")
    print(f"  {'-'*6} {'-'*20}  --------  ------")
    for r in cs[:5]:
        print(f"  {r['state']:<6s} {fmt_score(r['avg_score']):>20s}  "
              f"{r['neg_rate']:>7.1%}  {r['sample']:>6,d}")

    hr("【5b】最负面卖家州 Top 5")
    ss = s.get("by_seller_state") or []
    print(f"  {'state':<6s} {'avg_score':>20s}  neg_rate  sample")
    print(f"  {'-'*6} {'-'*20}  --------  ------")
    for r in ss[:5]:
        print(f"  {r['state']:<6s} {fmt_score(r['avg_score']):>20s}  "
              f"{r['neg_rate']:>7.1%}  {r['sample']:>6,d}")


# ═══════════════════════════════════════════════════════════════════════════
# 6: 主题 × 品类交叉
# ═══════════════════════════════════════════════════════════════════════════

def show_complaints_by_category(insight: dict):
    hr("【6】主题 × 品类交叉表（差评原因下钻：作业第 234 行验证问题）")
    cbc = insight.get("complaints_by_category") or []
    if not cbc:
        print("  样本不足，未生成此交叉表。")
        return
    print("  Top 差评品类及其主导差评原因（采样自 P0 抽样池）：\n")
    for i, c in enumerate(cbc[:10], 1):
        cat = c["category"][:40]
        dom = c["dominant_topic"]
        share = c["dominant_share"]
        total = c["total"]
        td = c.get("topic_distribution", {})
        print(f"  [{i:>2}] {cat:<40s} 差评 {total:>3d} 条 → 主因：{dom} ({share:.1%})")
        # 子分布
        sub = ", ".join(f"{k}={v}" for k, v in
                        sorted(td.items(), key=lambda x: -x[1])[:5])
        print(f"        ├─ 主题分布: {sub}")


# ═══════════════════════════════════════════════════════════════════════════
# 7: 词云数据
# ═══════════════════════════════════════════════════════════════════════════

def show_bertopic(insight: dict):
    hr("【7】BERTopic 无监督主题（远胜关键词法的 7 类预设）")
    bt = insight.get("topics_bertopic")
    if not bt or bt.get("method") == "n/a":
        print(f"  {bt.get('summary', '尚未灌库 BERTopic。运行 python -m agents.nlp_agent.tools.topic_model --backfill') if bt else '尚未生成。'}")
        return

    topics = bt.get("topics") or []
    print(f"  方法: {bt['method']}")
    print(f"  共发现 {len(topics)} 个有效主题（已排除离群点）\n")
    print(f"  {'#':>3} | {'count':>5} | {'label':<32} | top_words")
    print(f"  {'-'*3}-+-{'-'*5}-+-{'-'*32}-+-{'-'*40}")
    for t in topics[:15]:
        words = ", ".join(t["top_words"][:5])
        print(f"  {t['topic_id']:>3} | {t['sample_count']:>5} | {t['label']:<32} | {words}")

    print(f"\n  ── Top 差评品类 × 主导主题（差评原因下钻）──")
    for c in (bt.get("complaints_by_category") or [])[:6]:
        print(f"\n  {c['category']} - 差评 {c['total']:,d} 条")
        for r in c["top_reasons"]:
            bar_w = int(r["share"] * 25)
            print(f"    主题 {r['topic_id']:>2}: {r['label']:<30} "
                  f"{r['count']:>4d} ({r['share']:>5.1%}) {'█'*bar_w}")


def show_wordcloud(insight: dict):
    hr("【8】好评 / 差评 高频词对比（给 viz_agent 画对比词云）")
    wc = insight.get("wordcloud")
    if not wc or wc.get("method") == "n/a":
        print(f"  {wc.get('summary', '词云数据未生成。') if wc else '词云数据未生成。'}")
        return
    pos = wc.get("positive") or {}
    neg = wc.get("negative") or {}
    sample = wc.get("sample") or {}
    print(f"  抽样：好评 {sample.get('positive', 0)} 条，差评 {sample.get('negative', 0)} 条；"
          f"停用词 {wc.get('stopwords_count', 0)} 个；方法 {wc.get('method')}")

    print(f"\n  好评 Top 15:")
    for i, (w, c) in enumerate(list(pos.items())[:15], 1):
        print(f"    {i:>2}. {w:<20s}  {c:>5d}")

    print(f"\n  差评 Top 15:")
    for i, (w, c) in enumerate(list(neg.items())[:15], 1):
        print(f"    {i:>2}. {w:<20s}  {c:>5d}")

    only_neg = [w for w in list(neg.keys())[:30] if w not in pos]
    if only_neg:
        print(f"\n  差评特有词（差评 Top 30 ∖ 好评 Top 100）：{', '.join(only_neg[:15])}")


# ═══════════════════════════════════════════════════════════════════════════
# 8: NLP Agent 完整一次 run
# ═══════════════════════════════════════════════════════════════════════════

def run_full_agent():
    hr("【9】NLP Agent 完整一次运行（模拟 LangGraph 调度）")
    question = "Top 10 差评品类的主要原因和情感分布如何？"
    intent = "diagnostic"
    print(f"  question: {question}")
    print(f"  intent:   {intent}")
    print(f"  路由判定 should_run_nlp = {should_run_nlp(question, intent)}\n")

    state = {"question": question, "intent": intent}
    agent = ReviewInsightAgent(
        sample_size=1000,
        wordcloud_top_n=80,
        wordcloud_sample=4000,
    )
    state = agent.run(state)
    return state["review_insights"]


# ═══════════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "█" * 80)
    print("█  NLP Agent 完整能力演示")
    print("█  数据来源：MySQL agentic_bi（原始表 + review_sentiment 离线灌库 40,641 条）")
    print("█" * 80)

    # 1. 单条预测
    show_single_predictions()

    # 2~8. 完整 Agent 运行 + 拆解展示
    insight = run_full_agent()

    s = insight.get("sentiment") or {}
    if s.get("total"):
        show_sentiment_aggregations(s)
    else:
        hr("【2-5】sentiment 数据缺失")
        print(f"  {s.get('summary', '未生成 sentiment 数据。')}")

    show_complaints_by_category(insight)
    show_bertopic(insight)
    show_wordcloud(insight)

    hr("【顶层 summary】")
    print(f"  P0 主题摘要：{insight.get('summary', '')}")
    if s.get("summary"):
        print(f"  P1 情感摘要：{s['summary']}")
    bt = insight.get("topics_bertopic") or {}
    if bt.get("summary"):
        print(f"  P4 BERTopic 摘要：{bt['summary']}")
    if (insight.get("wordcloud") or {}).get("summary"):
        print(f"  P2 词云摘要：{insight['wordcloud']['summary']}")

    hr("END")
    print()


if __name__ == "__main__":
    main()
