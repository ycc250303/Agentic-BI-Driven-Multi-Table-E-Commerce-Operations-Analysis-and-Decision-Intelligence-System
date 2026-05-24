"""
P2：好评 / 差评对比词云数据生成。

从 `order_reviews` 中分别抽取：
- 好评（review_score >= 4）
- 差评（review_score <= 2）

两路评论文本各自做：
1. 文本规范化：转小写、去标点、去数字、去 URL、保留葡语带重音字符
2. 分词（按空白）+ 停用词过滤（来自 `config/nlp_agent/stopwords_pt.txt`）
3. 词频统计（默认 Top 100），输出 `{word: weight}`

输出契约：
    {
      "positive": {"otimo": 320, "rapido": 280, ...},
      "negative": {"atraso": 152, "defeito": 98, ...},
      "method": "1-gram + pt_stopwords",
      "sample": {"positive": 5000, "negative": 5000},
      "summary": "好评 / 差评高频词对比："
    }

直接对接 `agents/viz_agent`（其 wordcloud 渲染函数支持 `{word: weight}` 字典输入）。

CLI 用法：
    python -m agents.nlp_agent.tools.wordcloud_data --top 80 --sample 8000
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from agents.nlp_agent import db


# ---------------------------------------------------------------------------
# 文本规范化
# ---------------------------------------------------------------------------

# 葡语带重音字符 a-z + áàâãéêíóôõúüç
_TOKEN_RE = re.compile(r"[a-záàâãéêíóôõúüç]+", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+|www\.\S+")


def _normalize(text: str) -> list[str]:
    """评论文本 → 词列表（已小写、已去 URL / 数字 / 标点）。"""
    if not text:
        return []
    t = _URL_RE.sub(" ", text.lower())
    return _TOKEN_RE.findall(t)


# ---------------------------------------------------------------------------
# 停用词加载
# ---------------------------------------------------------------------------

_DEFAULT_STOPWORDS: set[str] = {
    "a", "as", "o", "os", "e", "de", "do", "da", "dos", "das",
    "um", "uma", "que", "para", "com", "em", "no", "na",
    "nao", "não", "mais", "muito", "tem", "ter", "foi", "ser",
    "produto", "pedido",
}


def _project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "config" / "nlp_agent").exists():
            return parent
    raise RuntimeError("未找到项目根目录下的 config/nlp_agent 目录。")


@lru_cache(maxsize=1)
def _load_stopwords() -> set[str]:
    try:
        path = _project_root() / "config" / "nlp_agent" / "stopwords_pt.txt"
        if not path.exists():
            return set(_DEFAULT_STOPWORDS)
        words: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            words.add(s.lower())
        return words or set(_DEFAULT_STOPWORDS)
    except Exception:
        return set(_DEFAULT_STOPWORDS)


# ---------------------------------------------------------------------------
# SQL：好评 / 差评抽样
# ---------------------------------------------------------------------------

_SAMPLE_SQL = """
SELECT review_comment_message
FROM order_reviews
WHERE review_score {score_filter}
  AND review_comment_message IS NOT NULL
  AND TRIM(review_comment_message) <> ''
  AND CHAR_LENGTH(review_comment_message) >= 5
ORDER BY RAND()
LIMIT %s
"""


def _fetch_messages(score_filter: str, sample: int) -> list[str]:
    sql = _SAMPLE_SQL.format(score_filter=score_filter)
    rows = db.query(sql, (int(sample),))
    return [str(r["review_comment_message"] or "") for r in rows]


# ---------------------------------------------------------------------------
# 词频统计
# ---------------------------------------------------------------------------


def _count_words(messages: list[str], stopwords: set[str], min_len: int = 3) -> Counter:
    counter: Counter = Counter()
    for msg in messages:
        for tok in _normalize(msg):
            if len(tok) < min_len:
                continue
            if tok in stopwords:
                continue
            counter[tok] += 1
    return counter


def _top_dict(counter: Counter, top_n: int) -> dict[str, int]:
    return {w: c for w, c in counter.most_common(top_n)}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def run_wordcloud_data(
    top_n: int = 100,
    pos_sample: int = 5000,
    neg_sample: int = 5000,
    min_word_len: int = 3,
) -> dict[str, Any]:
    """生成好评 / 差评对比词云数据。

    返回 dict 形态见模块 docstring。
    """
    stopwords = _load_stopwords()

    pos_msgs = _fetch_messages(">= 4", pos_sample)
    neg_msgs = _fetch_messages("<= 2", neg_sample)

    pos_cnt = _count_words(pos_msgs, stopwords, min_word_len)
    neg_cnt = _count_words(neg_msgs, stopwords, min_word_len)

    pos_words = _top_dict(pos_cnt, top_n)
    neg_words = _top_dict(neg_cnt, top_n)

    summary_parts = []
    if pos_words:
        top_pos = ", ".join(list(pos_words.keys())[:5])
        summary_parts.append(f"好评 Top 词：{top_pos}")
    if neg_words:
        top_neg = ", ".join(list(neg_words.keys())[:5])
        summary_parts.append(f"差评 Top 词：{top_neg}")

    return {
        "positive": pos_words,
        "negative": neg_words,
        "method": "1-gram + pt_stopwords",
        "sample": {
            "positive": len(pos_msgs),
            "negative": len(neg_msgs),
        },
        "stopwords_count": len(stopwords),
        "summary": "；".join(summary_parts) or "未抽到任何评论文本。",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="好评 / 差评对比词云数据生成")
    p.add_argument("--top", type=int, default=100, help="每路保留 Top N 高频词")
    p.add_argument("--pos-sample", type=int, default=5000, help="好评抽样上限")
    p.add_argument("--neg-sample", type=int, default=5000, help="差评抽样上限")
    p.add_argument("--min-len", type=int, default=3, help="忽略长度小于 N 的词")
    return p


def main() -> None:
    args = _parser().parse_args()
    out = run_wordcloud_data(
        top_n=args.top,
        pos_sample=args.pos_sample,
        neg_sample=args.neg_sample,
        min_word_len=args.min_len,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
