from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from agents.common.prompts import compose_system_prompt
from agents.coordinator_agent.orchestration.adapters import build_synthesis_evidence

logger = logging.getLogger(__name__)

EMPTY_FINAL_ANSWER = "未能生成回答，请查看 warnings。"


def _format_rows_fallback(evidence: dict) -> str:
    lines = [f"**{evidence.get('user_query', '')}**", ""]
    for item in evidence.get("sql_results") or []:
        q = item.get("question") or "查询"
        lines.append(f"### {q}")
        summary = item.get("business_summary")
        if summary:
            lines.append(str(summary))
        rows = item.get("key_rows") or []
        if rows:
            lines.append("")
            for i, row in enumerate(rows[:5], start=1):
                parts = [f"{k}={v}" for k, v in row.items()]
                lines.append(f"{i}. " + "，".join(parts))
        lines.append("")

    decision = evidence.get("decision_narrative")
    if decision:
        lines.extend(["### 建议", str(decision), ""])

    charts = evidence.get("charts") or []
    if charts:
        lines.append("### 图表")
        for c in charts:
            title = c.get("title") or c.get("chart_type") or "图表"
            lines.append(f"- {title}")

    return "\n".join(lines).strip()


def synthesize_final_answer(
    state: dict,
    *,
    model=None,
) -> tuple[str, str | None]:
    """撰写最终回答。默认 DeepSeek；失败或空文本回退规则摘要。返回 ``(answer, warning)``。"""
    evidence = build_synthesis_evidence(state)

    from agents.common.llm import invoke_chat

    system = compose_system_prompt("coordinator_agent", "synthesize_answer.md")
    human = (
        "【结构化证据】\n"
        + json.dumps(evidence, ensure_ascii=False, indent=2)
        + "\n\n请撰写面向业务人员的最终回答。"
    )
    try:
        text = invoke_chat(
            [SystemMessage(content=system), HumanMessage(content=human)],
            model=model,
        ).strip()
        if text:
            return text, None
        fallback = _format_rows_fallback(evidence)
        warning = "汇总 LLM 返回空文本，已回退规则摘要。"
        return fallback or EMPTY_FINAL_ANSWER, warning
    except Exception as exc:
        logger.warning("synthesize_final_answer 失败，已回退规则摘要：%s", exc)
        fallback = _format_rows_fallback(evidence)
        return (
            fallback or EMPTY_FINAL_ANSWER,
            f"汇总 LLM 失败，已回退规则摘要：{exc}",
        )
