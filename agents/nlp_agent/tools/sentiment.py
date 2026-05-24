"""
P1：评论文本情感分析工具。

设计要点
--------
1. **离线灌库 + 在线读库**：模型推理慢（每条 50~150 ms），不在用户请求路径上跑。
   - `backfill_sentiment(...)`：一次性把 `order_reviews` 全量跑完，写入 `review_sentiment` 表
   - `aggregate_sentiment(...)`：在线聚合查询，给 NLP Agent 返回情感分布、按品类/州分组等

2. **模型**：默认 `pysentimiento/robertuito-sentiment-analysis`（葡语 / 西语 / 英语原生，
   面向 Twitter/口语电商场景训练）。失败时降级使用 `cardiffnlp/twitter-xlm-roberta-base-sentiment`。

3. **`polarity_score` 综合分**：从三分类概率合成
       polarity_score = pos_prob - neg_prob   ∈ [-1, +1]

4. **幂等灌库**：使用 `INSERT ... ON DUPLICATE KEY UPDATE`，重复跑只会刷新；
   也可 `--only-missing` 只跑还没有落库的 review_id。

5. **进度反馈**：tqdm 进度条 + 每批 N 条打印一次实时统计（速率、ETA、累计分布）。

CLI
---
    # 试水：先跑 5000 条
    python -m agents.nlp_agent.tools.sentiment --backfill --limit 5000

    # 全量灌库（默认只灌 order_reviews 中带文本且尚未落库的评论）
    python -m agents.nlp_agent.tools.sentiment --backfill

    # 强制重新跑全量（覆盖现有 review_sentiment）
    python -m agents.nlp_agent.tools.sentiment --backfill --force

    # 在线聚合预览（不调模型，只读 review_sentiment 表）
    python -m agents.nlp_agent.tools.sentiment --aggregate
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any, Iterable

from agents.nlp_agent import db


logger = logging.getLogger("nlp.sentiment")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


# ---------------------------------------------------------------------------
# 模型加载（懒加载 + 兜底）
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "pysentimiento/robertuito-sentiment-analysis"
FALLBACK_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"


def _pick_torch_device():
    """优先 MPS（Apple Silicon GPU）→ CUDA → CPU。"""
    import torch  # type: ignore
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps"), "mps"
    if torch.cuda.is_available():
        return torch.device("cuda"), "cuda"
    return torch.device("cpu"), "cpu"


def _load_analyzer(model_name: str | None = None) -> tuple[Any, str]:
    """加载情感分析器；优先 pysentimiento（取其底层 model+tokenizer 直接做 batch 推理，
    绕过 pysentimiento 默认的 HF datasets 流水线 → 提速 15-30 倍），失败时退化为
    transformers pipeline。

    返回 `(analyzer, actual_model_name)`，其中 analyzer.predict_batch(list[str]) -> list[dict].
    `actual_model_name` 取自模型 config 的真实名（不再写死）。
    """
    name = model_name or DEFAULT_MODEL

    # ---- 路径 1：pysentimiento（推荐）：拿底层 model+tokenizer，自己批量推理 ----
    if "robertuito" in name or name == DEFAULT_MODEL:
        try:
            import torch  # type: ignore
            from pysentimiento import create_analyzer  # type: ignore

            logger.info("loading pysentimiento analyzer (lang=pt)…")
            analyzer = create_analyzer(task="sentiment", lang="pt")

            # 取底层 model + tokenizer；不同 pysentimiento 版本属性可能略有差异
            inner_model = getattr(analyzer, "model", None)
            inner_tok = getattr(analyzer, "tokenizer", None)
            inner_id2label = getattr(analyzer, "id2label", None) or {
                int(k): v for k, v in inner_model.config.id2label.items()
            }
            real_name = getattr(inner_model.config, "_name_or_path",
                                None) or DEFAULT_MODEL

            device, device_kind = _pick_torch_device()
            inner_model = inner_model.to(device)
            inner_model.eval()

            label_norm = {
                "POS": "POS", "NEG": "NEG", "NEU": "NEU",
                "POSITIVE": "POS", "NEGATIVE": "NEG", "NEUTRAL": "NEU",
            }

            class _FastWrapper:
                """直接走 transformers forward，避免 datasets/Map 开销。"""

                def __init__(self, m, t, id2label, device):
                    self.m = m
                    self.t = t
                    self.id2label = id2label
                    self.device = device

                @torch.no_grad()
                def predict_batch(self, texts):
                    if not texts:
                        return []
                    enc = self.t(
                        texts,
                        return_tensors="pt",
                        padding=True,
                        truncation=True,
                        max_length=128,
                    )
                    enc = {k: v.to(self.device) for k, v in enc.items()}
                    logits = self.m(**enc).logits
                    probs = torch.softmax(logits, dim=-1).detach().cpu().numpy()

                    items = []
                    for row in probs:
                        d = {"POS": 0.0, "NEU": 0.0, "NEG": 0.0}
                        for i, p in enumerate(row):
                            raw = str(self.id2label.get(i, "NEU")).upper()
                            key = label_norm.get(raw[:3], label_norm.get(raw, "NEU"))
                            d[key] = float(p)
                        top = max(d, key=d.get)
                        items.append({"label": top, "pos": d["POS"],
                                      "neu": d["NEU"], "neg": d["NEG"]})
                    return items

            logger.info("pysentimiento backend on device=%s, model=%s",
                        device_kind, real_name)
            return _FastWrapper(inner_model, inner_tok, inner_id2label, device), real_name
        except Exception as e:  # noqa: BLE001
            logger.warning("pysentimiento 加载失败：%s；尝试降级到 %s", e, FALLBACK_MODEL)
            name = FALLBACK_MODEL

    # ---- 路径 2：transformers pipeline 兜底 ----
    from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore
    import torch  # type: ignore

    logger.info("loading transformers pipeline: %s …", name)
    tok = AutoTokenizer.from_pretrained(name)
    mod = AutoModelForSequenceClassification.from_pretrained(name)
    device, device_kind = _pick_torch_device()
    mod = mod.to(device)
    mod.eval()

    real_name = getattr(mod.config, "_name_or_path", None) or name
    id2label = {int(k): str(v).upper()[:3] for k, v in mod.config.id2label.items()}
    label_map = {"POS": "POS", "NEG": "NEG", "NEU": "NEU",
                 "POSITIVE": "POS", "NEGATIVE": "NEG", "NEUTRAL": "NEU"}

    class _HFWrapper:
        def __init__(self, t, m, device):
            self.t = t
            self.m = m
            self.device = device

        @torch.no_grad()
        def predict_batch(self, texts):
            if not texts:
                return []
            enc = self.t(texts, return_tensors="pt", padding=True,
                         truncation=True, max_length=128)
            enc = {k: v.to(self.device) for k, v in enc.items()}
            logits = self.m(**enc).logits
            probs = torch.softmax(logits, dim=-1).detach().cpu().numpy()
            items = []
            for row in probs:
                d = {"POS": 0.0, "NEU": 0.0, "NEG": 0.0}
                for i, p in enumerate(row):
                    raw = id2label.get(i, "NEU")
                    key = label_map.get(raw, "NEU")
                    d[key] = float(p)
                top = max(d, key=d.get)
                items.append({"label": top, "pos": d["POS"],
                              "neu": d["NEU"], "neg": d["NEG"]})
            return items

    logger.info("HF backend on device=%s, model=%s", device_kind, real_name)
    return _HFWrapper(tok, mod, device), real_name


# ---------------------------------------------------------------------------
# 数据访问
# ---------------------------------------------------------------------------

_SQL_TODO = """
SELECT r.review_id, r.review_comment_message
FROM order_reviews r
LEFT JOIN review_sentiment s ON s.review_id = r.review_id
WHERE r.review_comment_message IS NOT NULL
  AND TRIM(r.review_comment_message) <> ''
  AND ({force_clause})
ORDER BY r.review_creation_date
{limit_clause}
"""


def _fetch_pending(only_missing: bool, limit: int | None) -> list[dict[str, Any]]:
    force_clause = "1=1" if not only_missing else "s.review_id IS NULL"
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    sql = _SQL_TODO.format(force_clause=force_clause, limit_clause=limit_clause)
    return db.query(sql)


_UPSERT_SQL = """
INSERT INTO review_sentiment
    (review_id, polarity, polarity_score, pos_prob, neu_prob, neg_prob,
     model_name, model_version)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    polarity = VALUES(polarity),
    polarity_score = VALUES(polarity_score),
    pos_prob = VALUES(pos_prob),
    neu_prob = VALUES(neu_prob),
    neg_prob = VALUES(neg_prob),
    model_name = VALUES(model_name),
    model_version = VALUES(model_version),
    created_at = CURRENT_TIMESTAMP
"""


def _bulk_upsert(rows: Iterable[tuple]) -> int:
    """批量 upsert；返回成功条数。"""
    rows = list(rows)
    if not rows:
        return 0
    import pymysql
    from pymysql.cursors import DictCursor
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from agents.sql_agent.tools.execute_sql import _db_config_from_env  # type: ignore

    cfg = _db_config_from_env()
    cfg["cursorclass"] = DictCursor
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 灌库主流程
# ---------------------------------------------------------------------------


def backfill_sentiment(
    limit: int | None = None,
    only_missing: bool = True,
    batch_size: int = 32,
    log_every_batches: int = 20,
    model_name: str | None = None,
) -> dict[str, Any]:
    """对 order_reviews 全量（或按 limit）跑情感模型并落库 review_sentiment。

    `only_missing=True`（默认）：只跑当前 review_sentiment 表里没有的评论（断点续跑友好）。
    `only_missing=False`：全量重跑（用于 --force）。
    """
    t0 = time.perf_counter()
    pending = _fetch_pending(only_missing=only_missing, limit=limit)
    total = len(pending)
    if total == 0:
        logger.info("没有待处理评论。only_missing=%s, limit=%s", only_missing, limit)
        return {"processed": 0, "skipped": 0, "elapsed_sec": 0.0,
                "avg_ms_per_review": 0.0}

    logger.info("待处理评论数：%d   batch_size=%d   only_missing=%s",
                total, batch_size, only_missing)

    analyzer, used_model = _load_analyzer(model_name)
    logger.info("model loaded: %s", used_model)

    pos_cnt = neu_cnt = neg_cnt = 0
    processed = 0
    last_log_t = time.perf_counter()
    last_log_n = 0

    # 进度条
    try:
        from tqdm import tqdm  # type: ignore
        pbar = tqdm(total=total, desc="sentiment", unit="rev",
                    bar_format="{l_bar}{bar:30}{r_bar}")
    except Exception:
        pbar = None

    for batch_idx, start in enumerate(range(0, total, batch_size)):
        chunk = pending[start:start + batch_size]
        texts = [str(r["review_comment_message"] or "")[:512] for r in chunk]

        try:
            preds = analyzer.predict_batch(texts)
        except Exception as e:  # noqa: BLE001
            logger.error("batch %d 推理失败，跳过：%s", batch_idx, e)
            if pbar:
                pbar.update(len(chunk))
            continue

        rows = []
        for r, p in zip(chunk, preds):
            polarity = (p.get("label") or "NEU").upper()[:3]
            if polarity not in ("POS", "NEU", "NEG"):
                polarity = "NEU"
            pos = float(p.get("pos", 0.0))
            neu = float(p.get("neu", 0.0))
            neg = float(p.get("neg", 0.0))
            score = pos - neg  # ∈ [-1, +1]
            rows.append((r["review_id"], polarity, score, pos, neu, neg,
                         used_model, None))
            if polarity == "POS":
                pos_cnt += 1
            elif polarity == "NEG":
                neg_cnt += 1
            else:
                neu_cnt += 1

        try:
            written = _bulk_upsert(rows)
            processed += written
        except Exception as e:  # noqa: BLE001
            logger.error("batch %d 入库失败：%s", batch_idx, e)

        if pbar:
            pbar.update(len(chunk))

        # 周期性反馈
        if (batch_idx + 1) % log_every_batches == 0:
            now = time.perf_counter()
            interval = now - last_log_t
            chunk_n = processed - last_log_n
            rate = chunk_n / max(interval, 1e-9)
            remaining = total - processed
            eta_min = remaining / max(rate, 1e-9) / 60.0
            logger.info(
                "[batch %4d] processed=%d/%d (%.1f%%) "
                "rate=%.1f rev/s  ETA≈%.1f min  "
                "POS=%d NEU=%d NEG=%d",
                batch_idx + 1, processed, total, processed / total * 100,
                rate, eta_min, pos_cnt, neu_cnt, neg_cnt,
            )
            last_log_t = now
            last_log_n = processed

    if pbar:
        pbar.close()

    elapsed = time.perf_counter() - t0
    avg_ms = elapsed * 1000.0 / max(processed, 1)
    logger.info(
        "DONE: processed=%d   POS=%d  NEU=%d  NEG=%d   "
        "elapsed=%.1f s   avg=%.1f ms/rev",
        processed, pos_cnt, neu_cnt, neg_cnt, elapsed, avg_ms,
    )
    return {
        "processed": processed,
        "pos": pos_cnt, "neu": neu_cnt, "neg": neg_cnt,
        "elapsed_sec": round(elapsed, 2),
        "avg_ms_per_review": round(avg_ms, 2),
        "model": used_model,
    }


# ---------------------------------------------------------------------------
# 在线聚合（NLP Agent 用）
# ---------------------------------------------------------------------------


_AGG_SQL = """
SELECT
    s.polarity,
    COUNT(*)               AS cnt,
    AVG(s.polarity_score)  AS avg_score,
    AVG(s.pos_prob)        AS avg_pos,
    AVG(s.neu_prob)        AS avg_neu,
    AVG(s.neg_prob)        AS avg_neg
FROM review_sentiment s
GROUP BY s.polarity
"""

_AGG_BY_REVIEW_SCORE_SQL = """
SELECT
    r.review_score,
    s.polarity,
    COUNT(*) AS cnt
FROM review_sentiment s
JOIN order_reviews r ON r.review_id = s.review_id
GROUP BY r.review_score, s.polarity
ORDER BY r.review_score, s.polarity
"""

_AGG_BY_CATEGORY_SQL = """
SELECT
    COALESCE(pct.product_category_name_english,
             p.product_category_name)            AS category,
    AVG(s.polarity_score)                        AS avg_score,
    SUM(CASE WHEN s.polarity='NEG' THEN 1 ELSE 0 END) / COUNT(*) AS neg_rate,
    COUNT(*)                                     AS sample
FROM review_sentiment s
JOIN order_reviews r   ON r.review_id = s.review_id
JOIN order_items   oi  ON oi.order_id = r.order_id
JOIN products      p   ON p.product_id = oi.product_id
LEFT JOIN product_category_name_translation pct
       ON pct.product_category_name = p.product_category_name
WHERE COALESCE(pct.product_category_name_english,
               p.product_category_name) IS NOT NULL
GROUP BY category
HAVING sample >= 30
ORDER BY avg_score ASC
LIMIT 10
"""

_AGG_BY_CUSTOMER_STATE_SQL = """
SELECT
    c.customer_state                             AS state,
    AVG(s.polarity_score)                        AS avg_score,
    SUM(CASE WHEN s.polarity='NEG' THEN 1 ELSE 0 END) / COUNT(*) AS neg_rate,
    COUNT(*)                                     AS sample
FROM review_sentiment s
JOIN order_reviews r ON r.review_id = s.review_id
JOIN orders o        ON o.order_id  = r.order_id
JOIN customers c     ON c.customer_id = o.customer_id
WHERE c.customer_state IS NOT NULL
GROUP BY c.customer_state
HAVING sample >= 30
ORDER BY avg_score ASC
"""

_AGG_BY_SELLER_STATE_SQL = """
SELECT
    sl.seller_state                              AS state,
    AVG(s.polarity_score)                        AS avg_score,
    SUM(CASE WHEN s.polarity='NEG' THEN 1 ELSE 0 END) / COUNT(*) AS neg_rate,
    COUNT(*)                                     AS sample
FROM review_sentiment s
JOIN order_reviews r ON r.review_id = s.review_id
JOIN order_items oi  ON oi.order_id = r.order_id
JOIN sellers sl      ON sl.seller_id = oi.seller_id
WHERE sl.seller_state IS NOT NULL
GROUP BY sl.seller_state
HAVING sample >= 30
ORDER BY avg_score ASC
"""

_MODEL_USED_SQL = """
SELECT model_name, COUNT(*) AS cnt
FROM review_sentiment
GROUP BY model_name
ORDER BY cnt DESC
LIMIT 1
"""


def aggregate_sentiment() -> dict[str, Any]:
    """从 review_sentiment 表读出聚合结果，给 NLP Agent 使用。"""
    overall = db.query(_AGG_SQL)
    by_score = db.query(_AGG_BY_REVIEW_SCORE_SQL)
    worst_categories = db.query(_AGG_BY_CATEGORY_SQL)
    by_customer_state = db.query(_AGG_BY_CUSTOMER_STATE_SQL)
    by_seller_state = db.query(_AGG_BY_SELLER_STATE_SQL)
    model_row = db.query(_MODEL_USED_SQL)
    used_model = model_row[0]["model_name"] if model_row else "unknown"

    total = sum(int(r["cnt"]) for r in overall) or 0
    polarity_dist = {r["polarity"]: int(r["cnt"]) for r in overall}
    if total:
        avg_score_all = sum(float(r["avg_score"]) * int(r["cnt"]) for r in overall) / total
    else:
        avg_score_all = 0.0

    pos = polarity_dist.get("POS", 0)
    neu = polarity_dist.get("NEU", 0)
    neg = polarity_dist.get("NEG", 0)

    summary = (
        f"已落库 {total} 条评论的情感分数：POS={pos}（{pos/total:.1%}），"
        f"NEU={neu}（{neu/total:.1%}），NEG={neg}（{neg/total:.1%}）；"
        f"加权平均极性={avg_score_all:+.3f}（-1 ~ +1）。"
        if total else "review_sentiment 表为空，请先运行 --backfill。"
    )

    def _fmt_state_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "state": r["state"],
                "avg_score": round(float(r["avg_score"]), 4),
                "neg_rate": round(float(r["neg_rate"]), 4),
                "sample": int(r["sample"]),
            }
            for r in rows
        ]

    return {
        "total": total,
        "polarity_distribution": polarity_dist,
        "avg_polarity_score": round(avg_score_all, 4),
        "by_review_score": [
            {"review_score": int(r["review_score"]),
             "polarity": r["polarity"], "count": int(r["cnt"])}
            for r in by_score
        ],
        "worst_categories": [
            {"category": r["category"],
             "avg_score": round(float(r["avg_score"]), 4),
             "neg_rate": round(float(r["neg_rate"]), 4),
             "sample": int(r["sample"])}
            for r in worst_categories
        ],
        "by_customer_state": _fmt_state_rows(by_customer_state),
        "by_seller_state": _fmt_state_rows(by_seller_state),
        "method": f"{used_model} (offline backfill)",
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="NLP 情感分析工具：离线灌库 + 在线聚合")
    p.add_argument("--backfill", action="store_true", help="对 order_reviews 跑模型并落库")
    p.add_argument("--aggregate", action="store_true", help="仅读 review_sentiment 聚合预览")
    p.add_argument("--limit", type=int, default=None, help="本次最多处理多少条")
    p.add_argument("--batch", type=int, default=32, help="批量大小（默认 32）")
    p.add_argument("--force", action="store_true",
                   help="强制重跑（默认只跑 review_sentiment 中尚未落库的）")
    p.add_argument("--model", type=str, default=None,
                   help=f"模型名（默认 {DEFAULT_MODEL}）")
    return p


def main() -> None:
    args = _parser().parse_args()

    if args.backfill:
        result = backfill_sentiment(
            limit=args.limit,
            only_missing=not args.force,
            batch_size=args.batch,
            model_name=args.model,
        )
        import json
        print("\n===== backfill summary =====")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.aggregate or not args.backfill:
        agg = aggregate_sentiment()
        import json
        print("\n===== aggregate =====")
        print(json.dumps(agg, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
