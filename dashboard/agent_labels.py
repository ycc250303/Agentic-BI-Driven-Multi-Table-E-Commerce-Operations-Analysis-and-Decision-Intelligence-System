from __future__ import annotations

AGENT_LABELS: dict[str, str] = {
    "decompose": "协调器 · 问题分解",
    "orchestrator": "协调器 · 任务调度",
    "data_analysis": "数据分析 Agent",
    "visualization": "可视化 Agent",
    "nlp": "评论洞察 Agent",
    "decision": "决策智能 Agent",
    "synthesize": "协调器 · 汇总回答",
}

SUB_AGENT_NODES = frozenset(
    {"data_analysis", "visualization", "nlp", "decision", "synthesize"}
)


def label_for(node_or_agent: str | None) -> str | None:
    if not node_or_agent:
        return None
    return AGENT_LABELS.get(node_or_agent, node_or_agent)
