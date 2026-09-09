from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from agents.common.paths import load_config_text
from agents.coordinator_agent.adapters import build_synthesis_evidence


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
    use_llm: bool = True,
) -> str:
    evidence = build_synthesis_evidence(state)
    if not use_llm:
        return _format_rows_fallback(evidence)

    from agents.common.llm import invoke_chat

    system = load_config_text("coordinator_agent", "synthesize_answer.md")
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
            return text
    except Exception:
        pass
    return _format_rows_fallback(evidence)
