from __future__ import annotations

import re

OFF_TOPIC_REFUSAL = (
    "本系统是 Olist 电商运营 BI 分析助手，只能回答与销售、订单、配送、支付、"
    "品类、卖家、评论及运营策略相关的数据问题。"
    "您的问题与 BI 分析无关（例如询问模型身份或使用特殊指令），我无法处理。"
    "请改用业务问题，例如：「2017 年各州销售额排名」「哪种支付方式最受欢迎」。"
)

_OFF_TOPIC_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"你是什么模型",
        r"你是谁",
        r"什么模型",
        r"哪个模型",
        r"用的什么\s*api",
        r"what\s+model",
        r"which\s+model",
        r"who\s+made\s+you",
        r"system\s*prompt",
        r"提示词",
        r"重复.*(规则|指令|prompt)",
        r"ignore\s+(all\s+)?previous",
        r"forget\s+(all\s+)?previous",
        r"忽略.*(规则|指令|上面)",
        r"从现在开始你",
        r"假装你是",
        r"jailbreak",
        r"\bdan\b",
        r"开发者模式",
        r"不受限制",
        r"/think\b",
        r"\\think",
        r"<\s*think\s*>",
    )
)

_BI_HINTS: tuple[str, ...] = (
    "gmv",
    "销售",
    "订单",
    "配送",
    "支付",
    "品类",
    "卖家",
    "评论",
    "差评",
    "准时",
    "olist",
    "电商",
    "运营",
    "州",
    "趋势",
    "排名",
    "预测",
    "策略",
    "改进",
    "运费",
    "review",
    "seller",
    "delivery",
    "payment",
)


def _has_bi_hint(text: str) -> bool:
    t = (text or "").lower()
    return any(h in t for h in _BI_HINTS)


def is_off_topic_query(user_query: str) -> bool:
    """规则层越界检测：明显非 BI 或注入式提问。"""
    text = (user_query or "").strip()
    if not text:
        return True
    if any(p.search(text) for p in _OFF_TOPIC_PATTERNS):
        if _has_bi_hint(text):
            return False
        return True
    if len(text) < 200 and not _has_bi_hint(text):
        chat_only = (
            "你好",
            "在吗",
            "hello",
            "hi",
            "讲个笑话",
            "写一首诗",
            "帮我写代码",
        )
        if any(text.lower().startswith(c) or text == c for c in chat_only):
            return True
    return False


def off_topic_state_patch(user_query: str) -> dict:
    return {
        "user_query": user_query,
        "question": user_query,
        "off_topic": True,
        "intent": "descriptive",
        "sub_questions": [],
        "suggested_agents": [],
        "task_plan": ["已识别为非 BI 业务问题，未调用子 Agent"],
        "plan_reasoning": "prompt_guardrails: off_topic",
        "final_answer": OFF_TOPIC_REFUSAL,
        "next_agent": "synthesize",
        "agents_done": {
            "data_analysis": True,
            "visualization": True,
            "nlp": True,
            "decision": True,
        },
    }
