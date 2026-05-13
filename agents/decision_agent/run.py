"""
Decision Intelligence Agent 入口：在 4-Agent 方案的末端，把 Data Analysis Agent
的产出与（可选的）预测 / 评论洞察 / What-if 模拟整合为面向业务人员的中文决策报告。

对外暴露：
- `DecisionIntelligenceAgent`：可独立 `run(state)` 的类。
- `decision_intelligence_node(state)`：LangGraph node 函数。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# 复用 sql_agent 中的 get_llm（DeepSeek + .env 加载）；延迟 import，便于离线/单测注入
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SQL_AGENT_DIR = _PROJECT_ROOT / "agents" / "sql_agent"
if str(_SQL_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_SQL_AGENT_DIR))


def _default_llm():
    from llm import get_llm  # noqa: WPS433 (sql_agent/llm.py)
    return get_llm()


from agents.decision_agent.tools.compose_report import ComposeReportRunner  # noqa: E402
from agents.decision_agent.tools.forecast import run_forecast  # noqa: E402
from agents.decision_agent.tools.review_insight import run_review_insight  # noqa: E402
from agents.decision_agent.tools.what_if import run_what_if  # noqa: E402


# ----------------------------------------------------------------------------
# 路由：根据问题与 intent 判断是否需要补充工具调用
# ----------------------------------------------------------------------------

_FORECAST_KEYWORDS = (
    "预测", "未来", "趋势", "下周", "下月", "未来6周", "未来 6 周",
    "forecast", "predict", "projection",
)
_REVIEW_KEYWORDS = (
    "评论", "差评", "评分", "抱怨", "原因", "满意度",
    "review", "negative", "complaint", "sentiment",
)
_WHAT_IF_KEYWORDS = (
    "如果", "假如", "下架", "提升多少", "降低多少",
    "what-if", "what if", "scenario",
)


def _has_kw(text: str, keywords: tuple[str, ...]) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords)


# ----------------------------------------------------------------------------
# Agent 主类
# ----------------------------------------------------------------------------


class DecisionIntelligenceAgent:
    """决策智能 Agent：对 4-Agent 方案末端的整合与建议生成。

    传入 `llm` 可注入自定义 LLM；不传则默认使用 sql_agent.llm.get_llm()。
    `tool_callbacks` 与 sql_agent 风格一致：每个内部步骤完成后会回调
    `(tool_name, json_or_text)`，便于 Web 实时推送。
    """

    def __init__(
        self,
        llm=None,
        forecast_fn: Callable[..., dict[str, Any]] = run_forecast,
        review_insight_fn: Callable[..., dict[str, Any]] = run_review_insight,
        what_if_fn: Callable[..., dict[str, Any]] = run_what_if,
    ):
        self.llm = llm or _default_llm()
        self._forecast_fn = forecast_fn
        self._review_insight_fn = review_insight_fn
        self._what_if_fn = what_if_fn
        self._compose = ComposeReportRunner(model=self.llm)

    # ----- 路由判断 -----
    @staticmethod
    def need_forecast(question: str, intent: str) -> bool:
        return intent == "predictive" or _has_kw(question, _FORECAST_KEYWORDS)

    @staticmethod
    def need_review_insight(question: str, intent: str) -> bool:
        return _has_kw(question, _REVIEW_KEYWORDS)

    @staticmethod
    def need_what_if(question: str, intent: str) -> bool:
        return intent == "what_if" or _has_kw(question, _WHAT_IF_KEYWORDS)

    # ----- 主入口 -----
    def run(
        self,
        state: dict[str, Any],
        on_tool_end: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        question = str(state.get("question", "") or "")
        intent = str(state.get("intent", "") or "")

        def emit(tool: str, payload: Any) -> None:
            if on_tool_end:
                on_tool_end(
                    tool,
                    payload if isinstance(payload, str)
                    else json.dumps(payload, ensure_ascii=False, indent=2),
                )

        # 1) 预测
        if self.need_forecast(question, intent) and "forecast_result" not in state:
            try:
                state["forecast_result"] = self._forecast_fn()
            except Exception as e:
                state["forecast_result"] = {
                    "method": "n/a",
                    "summary": f"预测工具执行失败：{e}",
                }
            emit("forecast_tool", state["forecast_result"])

        # 2) 评论洞察
        if self.need_review_insight(question, intent) and "review_insights" not in state:
            try:
                state["review_insights"] = self._review_insight_fn()
            except Exception as e:
                state["review_insights"] = {
                    "method": "n/a",
                    "summary": f"评论洞察工具执行失败：{e}",
                }
            emit("review_insight_tool", state["review_insights"])

        # 3) What-if
        if self.need_what_if(question, intent) and "what_if_result" not in state:
            try:
                state["what_if_result"] = self._what_if_fn()
            except Exception as e:
                state["what_if_result"] = {
                    "scenario": "n/a",
                    "summary": f"What-if 工具执行失败：{e}",
                }
            emit("what_if_tool", state["what_if_result"])

        # 4) 组装最终报告
        # 仅向 LLM 暴露已知字段，避免把整张 state（含历史会话等）一股脑塞进上下文
        report_state = {
            "question": question,
            "intent": intent,
            "analysis_summary": state.get("analysis_summary", ""),
            "sql_results": state.get("sql_results"),
            "chart_paths": state.get("chart_paths"),
            "chart_descriptions": state.get("chart_descriptions"),
            "forecast_result": state.get("forecast_result"),
            "review_insights": state.get("review_insights"),
            "what_if_result": state.get("what_if_result"),
        }
        report = self._compose.invoke(json.dumps(report_state, ensure_ascii=False))
        state["decision_report"] = report
        state["final_answer"] = report
        emit("compose_report_tool", report)

        return state


# ----------------------------------------------------------------------------
# LangGraph node：保持函数签名 state -> state，便于 add_node("decision", ...)
# ----------------------------------------------------------------------------


def decision_intelligence_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node：使用默认 LLM 与默认工具构造 Agent，写回更新后的 state。"""
    return DecisionIntelligenceAgent().run(state)


if __name__ == "__main__":
    # 简单冒烟：不连库不调 LLM 的离线版本（mock 三个工具）
    demo_state = {
        "question": "如果将 Top 20 高差评卖家的商品下架，平台评分能提升多少？",
        "intent": "what_if",
        "analysis_summary": "已统计当前平台 GMV 与差评率（示例摘要）。",
        "sql_results": [
            {
                "name": "platform_kpi",
                "explanation": "近 12 个月平台总体 KPI",
                "columns": ["total_gmv", "avg_review_score", "negative_rate"],
                "row_count": 1,
                "sample_rows": [
                    {"total_gmv": 12345678.9, "avg_review_score": 4.05, "negative_rate": 0.18}
                ],
            }
        ],
        "chart_paths": ["./charts/score_dist.png"],
        "chart_descriptions": ["全平台评分分布柱状图"],
    }

    class _FakeLLM:
        def invoke(self, messages):
            class _R:
                content = "（演示输出）由于未配置真实 LLM，此处省略八节模板内容。"
            return _R()

    agent = DecisionIntelligenceAgent(
        llm=_FakeLLM(),
        forecast_fn=lambda: {"method": "stub", "summary": "stub forecast"},
        review_insight_fn=lambda: {"method": "stub", "summary": "stub review"},
        what_if_fn=lambda: {
            "scenario": "stub",
            "current_avg_score": 4.05,
            "simulated_avg_score": 4.18,
            "estimated_score_improvement": 0.13,
            "summary": "stub what-if",
        },
    )

    out = agent.run(demo_state, on_tool_end=lambda t, p: print(f"\n=== {t} ===\n{p}"))
    print("\n===== final_answer =====")
    print(out["final_answer"])
