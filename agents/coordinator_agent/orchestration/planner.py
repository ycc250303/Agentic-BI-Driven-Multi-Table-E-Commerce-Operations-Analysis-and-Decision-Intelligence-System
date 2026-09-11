from __future__ import annotations

from typing import Literal

IntentName = Literal[
    "descriptive", "diagnostic", "predictive", "prescriptive", "what_if"
]

_INTENT_RULES: list[tuple[IntentName, tuple[str, ...]]] = [
    (
        "prescriptive",
        (
            "如何",
            "怎么",
            "策略",
            "方案",
            "改进",
            "优化",
            "建议",
            "优先",
            "三大",
            "运营改进",
            "降低",
        ),
    ),
    ("predictive", ("预测", "未来", "forecast", "prophet", "外推", "接下来")),
    (
        "diagnostic",
        (
            "为什么",
            "原因",
            "诊断",
            "哪些卖家",
            "差评率",
            "差评",
            "差评品类",
            "差评原因",
            "延迟严重",
            "显著高于",
            "根本原因",
        ),
    ),
]


def _has_kw(text: str, keywords: tuple[str, ...]) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords)


def classify_intent(user_query: str) -> IntentName:
    for intent, keywords in _INTENT_RULES:
        if _has_kw(user_query, keywords):
            return intent
    return "descriptive"
