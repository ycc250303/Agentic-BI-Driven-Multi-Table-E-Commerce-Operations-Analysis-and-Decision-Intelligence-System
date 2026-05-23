"""
Compose Report 工具：把 question / intent / sql_results 摘要 / chart_descriptions /
forecast_result / review_insights / what_if_result 组装成 LLM 输入，
按 config/decision_agent/decision_report.md 的八节模板生成中文决策报告。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool

from agents.decision_agent.state import summarize_sql_results


def _project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config" / "decision_agent").exists():
            return parent
    raise RuntimeError("未找到项目根目录下的 config/decision_agent 目录。")


@lru_cache(maxsize=4)
def _load_prompt(name: str) -> str:
    p = _project_root() / "config" / "decision_agent" / name
    return p.read_text(encoding="utf-8")


def _build_payload(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": state.get("question", ""),
        "intent": state.get("intent", ""),
        "analysis_summary": state.get("analysis_summary", ""),
        "sql_results_brief": summarize_sql_results(state.get("sql_results")),
        "chart_descriptions": list(state.get("chart_descriptions") or []),
        "chart_paths": list(state.get("chart_paths") or []),
        "forecast_result": state.get("forecast_result"),
        "review_insights": state.get("review_insights"),
        "what_if_result": state.get("what_if_result"),
    }


class ComposeReportRunner:
    def __init__(self, model):
        self.model = model

    def invoke(self, state_json: str) -> str:
        state = json.loads(state_json)
        payload = _build_payload(state)

        system_prompt = "\n\n".join(
            [
                "# Agent 背景规则",
                _load_prompt("system_core.md"),
                "# 决策报告生成规则",
                _load_prompt("decision_report.md"),
            ]
        )
        human_content = (
            "以下为本轮分析的全部已知输入（JSON），请按八节模板生成中文决策报告：\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_content),
        ]
        resp = self.model.invoke(messages)
        # langchain BaseMessage 的 content 既可能是 str 也可能是 list；统一成 str
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return content.strip()


def build_compose_report_tool(model) -> StructuredTool:
    runner = ComposeReportRunner(model=model)
    return StructuredTool.from_function(
        func=runner.invoke,
        name="compose_report_tool",
        description=(
            "把 LangGraph state（JSON 字符串）转为结构化中文决策报告。"
            "需要 state 中包含 question/intent/analysis_summary/sql_results/chart_descriptions 等字段。"
        ),
    )
