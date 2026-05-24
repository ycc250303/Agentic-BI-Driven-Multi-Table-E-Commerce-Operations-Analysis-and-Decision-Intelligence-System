"""
P4：BERTopic 无监督主题建模工具。

设计与 sentiment.py 类似（**离线训练 + 在线读表**）：
- `backfill_topics(...)`：抽取 review_score<=2 的差评（约 1.4 万条），用多语种
  sentence-transformers embedding → UMAP 降维 → HDBSCAN 聚类 → c-TF-IDF 提关键词，
  一次性落库到 `review_topics`（评论级）+ `review_topic_meta`（主题级）。

- `aggregate_bertopic(...)`：在线读表，按 (品类 × 主题) 双维度聚合，输出"X 品类
  的差评 38% 是物流损坏"这种结构化结果，供 NLP Agent 写入
  `state["review_insights"]["topics_bertopic"]`。

模型：
- Embedding：`paraphrase-multilingual-MiniLM-L12-v2`（多语种，葡语友好，~120MB）
- 聚类：BERTopic 默认 UMAP + HDBSCAN
- 关键词：c-TF-IDF（BERTopic 内置）
- 离群点（topic_id=-1）：HDBSCAN 自然产物，代表"识别不出聚类"的零散评论；
  本工具会把它们一并落库（label=outlier），便于诊断 / 后续过滤。

CLI:
    # 离线训练 + 灌库（首次运行下载 ~120MB embedding 模型；约 5-10 分钟）
    python -m agents.nlp_agent.tools.topic_model --backfill

    # 限制样本数试水
    python -m agents.nlp_agent.tools.topic_model --backfill --limit 2000

    # 自定义主题数（默认 auto，由 HDBSCAN 决定；如想固定 15 个主题）
    python -m agents.nlp_agent.tools.topic_model --backfill --nr-topics 15

    # 在线聚合预览（不调模型）
    python -m agents.nlp_agent.tools.topic_model --aggregate
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any

from agents.nlp_agent import db


logger = logging.getLogger("nlp.topic_model")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


# 训练用差评（带文本，过滤极短文本以避免 embedding 噪声）
_FETCH_NEG_REVIEWS_SQL = """
SELECT review_id, review_comment_message
FROM order_reviews
WHERE review_score <= 2
  AND review_comment_message IS NOT NULL
  AND CHAR_LENGTH(TRIM(review_comment_message)) >= 10
ORDER BY review_creation_date
{limit_clause}
"""


EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


# ---------------------------------------------------------------------------
# DB upsert helpers
# ---------------------------------------------------------------------------


def _bulk_upsert_review_topics(rows: list[tuple]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO review_topics
        (review_id, topic_id, probability, model_name)
    VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        topic_id   = VALUES(topic_id),
        probability= VALUES(probability),
        model_name = VALUES(model_name),
        created_at = CURRENT_TIMESTAMP
    """
    return _executemany(sql, rows)


def _bulk_upsert_topic_meta(rows: list[tuple]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO review_topic_meta
        (topic_id, label, top_words_json, sample_count, model_name)
    VALUES (%s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        label          = VALUES(label),
        top_words_json = VALUES(top_words_json),
        sample_count   = VALUES(sample_count),
        created_at     = CURRENT_TIMESTAMP
    """
    return _executemany(sql, rows)


def _executemany(sql: str, rows: list[tuple]) -> int:
    """与 sentiment.py 相同的写库套路：复用 sql_agent 环境变量解析。"""
    import pymysql
    from pymysql.cursors import DictCursor

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from agents.sql_agent.tools.execute_sql import _db_config_from_env  # type: ignore

    cfg = _db_config_from_env()
    cfg["cursorclass"] = DictCursor
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 训练 + 灌库
# ---------------------------------------------------------------------------


def backfill_topics(
    limit: int | None = None,
    nr_topics: int | str | None = None,
    min_topic_size: int = 30,
    embedding_model: str = EMBEDDING_MODEL,
    top_words_per_topic: int = 10,
) -> dict[str, Any]:
    """对差评全量做 BERTopic 训练 + 落库。

    - `limit`: 抽样上限，None 则全量
    - `nr_topics`: BERTopic 的 nr_topics 参数，None 表示由 HDBSCAN 自动决定；
      传整数则训练后会"减少"到指定数量；'auto' 会让 BERTopic 自己合并相近主题。
    - `min_topic_size`: HDBSCAN 的最小簇大小（每个主题至少这么多条评论）
    """
    t0 = time.perf_counter()

    # 1) 取数据
    sql = _FETCH_NEG_REVIEWS_SQL.format(
        limit_clause=f"LIMIT {int(limit)}" if limit else ""
    )
    rows = db.query(sql)
    if not rows:
        logger.warning("没有差评样本可用于训练。")
        return {"trained": 0, "topics": 0, "elapsed_sec": 0.0}

    review_ids = [str(r["review_id"]) for r in rows]
    docs = [str(r["review_comment_message"] or "") for r in rows]
    logger.info("loaded %d negative reviews for BERTopic training", len(docs))

    # 2) 加载 embedding 模型（首次会下载）
    from sentence_transformers import SentenceTransformer  # type: ignore

    logger.info("loading sentence-transformers: %s …", embedding_model)
    embedder = SentenceTransformer(embedding_model)
    logger.info("encoding %d documents into embeddings…", len(docs))
    embeddings = embedder.encode(
        docs, show_progress_bar=True, batch_size=64, convert_to_numpy=True,
    )
    logger.info("embeddings done, shape=%s", embeddings.shape)

    # 3) 配置并训练 BERTopic
    from bertopic import BERTopic  # type: ignore
    from hdbscan import HDBSCAN  # type: ignore

    hdbscan_model = HDBSCAN(
        min_cluster_size=min_topic_size,
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )

    bert_kwargs: dict[str, Any] = {
        "embedding_model": embedder,
        "hdbscan_model": hdbscan_model,
        "calculate_probabilities": True,
        "verbose": True,
    }
    if isinstance(nr_topics, int) and nr_topics > 0:
        bert_kwargs["nr_topics"] = nr_topics
    elif nr_topics == "auto":
        bert_kwargs["nr_topics"] = "auto"

    topic_model = BERTopic(**bert_kwargs)
    logger.info("training BERTopic …")
    topic_ids, probs = topic_model.fit_transform(docs, embeddings)
    logger.info("training done. unique topics: %d (incl. -1 outlier)",
                len(set(topic_ids)))

    # 4) 整理评论 → 主题 落库行
    topic_review_rows: list[tuple] = []
    for rid, tid, p in zip(review_ids, topic_ids, probs):
        # probs 可能是 None（calculate_probabilities=False 时）或一维数组
        try:
            score = float(p) if p is not None and not hasattr(p, "__len__") else (
                float(max(p)) if p is not None else None
            )
        except Exception:
            score = None
        topic_review_rows.append((rid, int(tid), score, embedding_model))

    # 5) 整理主题元信息行
    info_df = topic_model.get_topic_info()  # Topic, Count, Name
    topic_meta_rows: list[tuple] = []
    for _, row in info_df.iterrows():
        tid = int(row["Topic"])
        count = int(row["Count"])
        if tid == -1:
            label = "outlier"
            top_words = []
        else:
            top_pairs = topic_model.get_topic(tid) or []
            top_words = [{"word": str(w), "weight": float(s)}
                         for w, s in top_pairs[:top_words_per_topic]]
            label = " / ".join(p["word"] for p in top_words[:3]) or f"topic_{tid}"
        topic_meta_rows.append((
            tid, label[:128],
            json.dumps(top_words, ensure_ascii=False)[:65000],
            count, embedding_model,
        ))

    # 6) 写库
    logger.info("writing %d review_topics rows + %d review_topic_meta rows…",
                len(topic_review_rows), len(topic_meta_rows))
    _bulk_upsert_review_topics(topic_review_rows)
    _bulk_upsert_topic_meta(topic_meta_rows)

    elapsed = time.perf_counter() - t0
    logger.info("DONE in %.1f s. topics=%d  trained_reviews=%d",
                elapsed, len(topic_meta_rows), len(topic_review_rows))

    return {
        "trained": len(topic_review_rows),
        "topics": len(topic_meta_rows),
        "elapsed_sec": round(elapsed, 2),
        "embedding_model": embedding_model,
        "outlier_count": sum(1 for tid in topic_ids if int(tid) == -1),
    }


# ---------------------------------------------------------------------------
# 在线聚合
# ---------------------------------------------------------------------------


_TOPIC_OVERVIEW_SQL = """
SELECT m.topic_id, m.label, m.sample_count, m.top_words_json
FROM review_topic_meta m
WHERE m.topic_id <> -1
ORDER BY m.sample_count DESC
LIMIT %s
"""

_TOPIC_BY_CATEGORY_SQL = """
SELECT
    COALESCE(pct.product_category_name_english,
             p.product_category_name) AS category,
    rt.topic_id,
    COUNT(*)                          AS cnt
FROM review_topics rt
JOIN order_reviews r ON r.review_id = rt.review_id
JOIN order_items oi  ON oi.order_id = r.order_id
JOIN products p      ON p.product_id = oi.product_id
LEFT JOIN product_category_name_translation pct
       ON pct.product_category_name = p.product_category_name
WHERE COALESCE(pct.product_category_name_english,
               p.product_category_name) IS NOT NULL
  AND rt.topic_id <> -1
GROUP BY category, rt.topic_id
"""


def aggregate_bertopic(top_topics: int = 12,
                      top_categories: int = 10) -> dict[str, Any]:
    """从 review_topics + review_topic_meta 聚合，给 NLP Agent 用。"""
    overview = db.query(_TOPIC_OVERVIEW_SQL, (int(top_topics),))
    if not overview:
        return {
            "method": "bertopic",
            "summary": "review_topic_meta 为空，请先运行 --backfill。",
            "topics": [],
            "complaints_by_category": [],
        }

    cat_rows = db.query(_TOPIC_BY_CATEGORY_SQL)

    # 主题列表（含 Top 关键词）
    topics: list[dict[str, Any]] = []
    for r in overview:
        try:
            words = json.loads(r["top_words_json"] or "[]")
        except Exception:
            words = []
        topics.append({
            "topic_id": int(r["topic_id"]),
            "label": r["label"],
            "sample_count": int(r["sample_count"]),
            "top_words": [w.get("word") for w in words[:8]],
        })

    # topic_id → label 映射
    label_map = {t["topic_id"]: t["label"] for t in topics}

    # 按品类聚合：每个品类的差评在各主题上的分布
    grid: dict[str, dict[int, int]] = {}
    cat_total: dict[str, int] = {}
    for row in cat_rows:
        cat = row["category"]
        tid = int(row["topic_id"])
        cnt = int(row["cnt"])
        if tid not in label_map:  # 只算入选 top_topics 的主题
            continue
        grid.setdefault(cat, {})[tid] = cnt
        cat_total[cat] = cat_total.get(cat, 0) + cnt

    # 取 Top N 品类
    cat_ranked = sorted(cat_total.items(), key=lambda x: -x[1])[:top_categories]
    complaints_by_category: list[dict[str, Any]] = []
    for cat, total in cat_ranked:
        if total == 0:
            continue
        topic_dist = grid[cat]
        # 取每个品类的 Top 3 主题
        sorted_topics = sorted(topic_dist.items(), key=lambda x: -x[1])[:3]
        top_reasons = [
            {
                "topic_id": tid,
                "label": label_map[tid],
                "count": cnt,
                "share": round(cnt / total, 4),
            }
            for tid, cnt in sorted_topics
        ]
        complaints_by_category.append({
            "category": cat,
            "total": total,
            "top_reasons": top_reasons,
        })

    summary = (
        f"BERTopic 在差评全量上发现了 {len(topics)} 个有效主题（已排除离群点）；"
        f"Top {min(3, len(topics))} 主题为：" +
        "、".join(f"「{t['label']}」({t['sample_count']})"
                  for t in topics[:3]) + "。"
    )

    return {
        "method": f"bertopic + {EMBEDDING_MODEL}",
        "summary": summary,
        "topics": topics,
        "complaints_by_category": complaints_by_category,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="NLP BERTopic 主题建模工具")
    p.add_argument("--backfill", action="store_true", help="训练 + 落库")
    p.add_argument("--aggregate", action="store_true", help="在线聚合预览")
    p.add_argument("--limit", type=int, default=None, help="训练样本上限")
    p.add_argument("--nr-topics", default=None,
                   help="主题数：整数 / 'auto' / 不传=自动决定")
    p.add_argument("--min-topic-size", type=int, default=30,
                   help="HDBSCAN min_cluster_size（默认 30）")
    p.add_argument("--top-topics", type=int, default=12, help="aggregate 时取 Top N 主题")
    return p


def main() -> None:
    args = _parser().parse_args()

    if args.backfill:
        nr_topics = args.nr_topics
        if nr_topics is not None and nr_topics != "auto":
            try:
                nr_topics = int(nr_topics)
            except ValueError:
                pass
        result = backfill_topics(
            limit=args.limit,
            nr_topics=nr_topics,
            min_topic_size=args.min_topic_size,
        )
        print("\n===== backfill summary =====")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.aggregate or not args.backfill:
        agg = aggregate_bertopic(top_topics=args.top_topics)
        print("\n===== aggregate =====")
        print(json.dumps(agg, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
