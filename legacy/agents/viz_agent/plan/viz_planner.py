"""套件规划入口：LLM / 启发式出任务清单，再交给规则后处理。"""

from __future__ import annotations

import json
import logging
from typing import Any

from agents.common.prompts import compose_system_prompt
from agents.viz_agent.plan.columns import (
    _is_scalar_kpi_result,
    _sql_result_rows_from_payload,
    _sql_run_payload,
    _summarize_sql_runs,
    build_column_profiles_for_viz,
    extract_columns_from_exec_payload,
)
from agents.viz_agent.plan.postprocess import (
    _dedupe_viz_charts,
    _enrich_diagnostic_review_charts,
    _finalize_sql_chart_tasks,
    _has_global_compare_wordcloud,
    _infer_hint_from_columns,
    _strip_unrenderable_insight_charts,
)
from agents.viz_agent.plan.tasks import (
    ChartHint,
    DataSource,
    InsightChartType,
    VizChartTask,
    VizSuitePlan,
    _COMPREHENSIVE_HINTS,
    _REVIEW_VIZ_HINTS,
    _VIZ_HINTS,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ChartHint",
    "DataSource",
    "InsightChartType",
    "VizChartTask",
    "VizSuitePlan",
    "build_column_profiles_for_viz",
    "extract_columns_from_exec_payload",
    "heuristic_viz_suite",
    "plan_viz_suite",
    "plan_viz_suite_llm",
    "query_suggests_visualization",
]


def query_suggests_visualization(user_query: str, intent: str) -> bool:
    """问句/意图是否像要图。分解补 suggested_agents、路由、套件规划跳过都读这个。"""
    q = user_query or ""
    ql = q.lower()
    if intent in ("predictive", "diagnostic"):
        return True
    if any(h in q or h in ql for h in _REVIEW_VIZ_HINTS):
        return True
    if any(h in q or h in ql for h in _COMPREHENSIVE_HINTS):
        return True
    return any(h in q or h in ql for h in _VIZ_HINTS)


def _build_planner_context(
    *,
    user_query: str,
    intent: str,
    sql_runs: list[dict[str, Any]],
    review_insights: dict[str, Any] | None = None,
) -> str:
    """把 sql_runs 压成规划器 Human 上下文：列名、行数、摘要、视图，不把整份 CSV 塞进 Prompt。"""
    nlp_summary: dict[str, Any] = {}
    if review_insights:
        nlp_summary = {
            "summary": review_insights.get("summary"),
            "topic_distribution": review_insights.get("topic_distribution"),
            "top_categories": review_insights.get("top_categories"),
            "complaints_by_category_sample": (review_insights.get("complaints_by_category") or [])[:5],
        }
    return json.dumps(
        {
            "user_query": user_query,
            "intent": intent,
            "sql_runs": _summarize_sql_runs(sql_runs),
            "review_insights": nlp_summary or None,
        },
        ensure_ascii=False,
        indent=2,
    )


def heuristic_viz_suite(
    *,
    user_query: str,
    intent: str,
    sql_runs: list[dict[str, Any]],
    review_insights: dict[str, Any] | None = None,
) -> VizSuitePlan:
    if not sql_runs:
        return VizSuitePlan(
            needs_visualization=False,
            reasoning="尚无 SQL 分析结果，无法规划图表。",
        )
    if not query_suggests_visualization(user_query, intent):
        return VizSuitePlan(
            needs_visualization=False,
            reasoning="问题以单一指标/事实答复为主，无需额外图表。",
        )

    comprehensive = any(h in user_query for h in _COMPREHENSIVE_HINTS)
    max_charts = 5 if comprehensive else min(3, len(sql_runs))

    charts: list[VizChartTask] = []
    for i, run in enumerate(sql_runs[:max_charts]):
        summary = _summarize_sql_runs([run])[0]
        if not summary.get("ok") or not summary.get("columns"):
            continue
        payload = _sql_run_payload(sql_runs, i)
        if payload:
            rows = _sql_result_rows_from_payload(payload)
            if rows and all(_is_scalar_kpi_result(r) for r in rows):
                continue
        cols = summary["columns"]
        hint = _infer_hint_from_columns(cols, str(run.get("question") or user_query))
        include_fc = intent == "predictive" or any(
            k in user_query for k in ("预测", "未来", "6周", "六周")
        )
        charts.append(
            VizChartTask(
                title=str(run.get("question") or f"分析结果图 {i + 1}").rstrip("？"),
                rationale=f"基于子问题「{run.get('question')}」的查数结果可视化",
                data_source="sql_run",
                sql_run_index=i,
                chart_type_hint=hint,
                include_forecast=include_fc and hint == "line",
            )
        )

    charts = _finalize_sql_chart_tasks(
        charts,
        sql_runs=sql_runs,
        user_query=user_query,
        intent=intent,
    )

    if any(k in user_query for k in ("评论", "差评", "词云", "口碑", "review")) and not _has_global_compare_wordcloud(
        charts
    ):
        charts.append(
            VizChartTask(
                title="好评与差评评论词云对比",
                rationale="用户关注评论文本差异",
                data_source="wordcloud",
                chart_type_hint="wordcloud",
            )
        )

    if intent == "diagnostic" or any(k in user_query for k in _REVIEW_VIZ_HINTS):
        charts = _enrich_diagnostic_review_charts(
            user_query=user_query,
            charts=charts,
            review_insights=review_insights,
            sql_runs=sql_runs,
        )

    if not charts:
        return VizSuitePlan(
            needs_visualization=False,
            reasoning="SQL 结果不可用或不适合制图。",
        )

    charts = _strip_unrenderable_insight_charts(charts, review_insights)
    charts = _dedupe_viz_charts(charts, sql_runs=sql_runs)
    return VizSuitePlan(
        needs_visualization=True,
        reasoning=f"规则规划：用户问题需要 {len(charts)} 张图辅助说明。",
        charts=charts,
    )


def plan_viz_suite_llm(
    *,
    user_query: str,
    intent: str,
    sql_runs: list[dict[str, Any]],
    review_insights: dict[str, Any] | None = None,
    model=None,
) -> VizSuitePlan:
    """结构化输出套件计划（Prompt: config/visualization_agent/plan_suite.md）。

    LLM 只决定 needs_visualization 与 charts[]（data_source / 类型 hint）。
    返回前仍走规则后处理，避免漏图或画不出的洞察图。
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.common.llm import invoke_structured

    system = compose_system_prompt("visualization_agent", "plan_suite.md")
    human = (
        f"【用户问题】\n{user_query}\n\n"
        f"【intent】\n{intent}\n\n"
        f"【已完成分析】\n{_build_planner_context(user_query=user_query, intent=intent, sql_runs=sql_runs, review_insights=review_insights)}\n\n"
        "请只输出结构化出图规划。"
    )
    response = invoke_structured(
        VizSuitePlan,
        [SystemMessage(content=system), HumanMessage(content=human)],
        model=model,
    )
    plan = (
        response
        if isinstance(response, VizSuitePlan)
        else VizSuitePlan.model_validate(response)
    )
    charts = _finalize_sql_chart_tasks(
        list(plan.charts),
        sql_runs=sql_runs,
        user_query=user_query,
        intent=intent,
    )
    if intent == "diagnostic" or any(k in user_query for k in _REVIEW_VIZ_HINTS):
        charts = _enrich_diagnostic_review_charts(
            user_query=user_query,
            charts=charts,
            review_insights=review_insights,
            sql_runs=sql_runs,
        )
    charts = _strip_unrenderable_insight_charts(charts, review_insights)
    charts = _dedupe_viz_charts(charts, sql_runs=sql_runs)
    if not charts:
        return heuristic_viz_suite(
            user_query=user_query,
            intent=intent,
            sql_runs=sql_runs,
            review_insights=review_insights,
        )
    plan = plan.model_copy(
        update={
            "needs_visualization": True,
            "charts": charts,
        }
    )
    return plan


def plan_viz_suite(
    *,
    user_query: str,
    intent: str,
    sql_runs: list[dict[str, Any]],
    review_insights: dict[str, Any] | None = None,
    model=None,
) -> VizSuitePlan:
    """套件规划：默认 DeepSeek 结构化输出；失败或诊断空计划时回退启发式。"""
    if not query_suggests_visualization(user_query, intent) and intent not in ("predictive",):
        return VizSuitePlan(
            needs_visualization=False,
            reasoning="问题未体现可视化需求，跳过出图。",
        )
    try:
        plan = plan_viz_suite_llm(
            user_query=user_query,
            intent=intent,
            sql_runs=sql_runs,
            review_insights=review_insights,
            model=model,
        )
        if intent == "diagnostic" and (not plan.needs_visualization or not plan.charts):
            return heuristic_viz_suite(
                user_query=user_query,
                intent=intent,
                sql_runs=sql_runs,
                review_insights=review_insights,
            )
        return plan
    except Exception as exc:
        logger.warning("plan_viz_suite LLM 失败，已回退启发式：%s", exc)
        heuristic = heuristic_viz_suite(
            user_query=user_query,
            intent=intent,
            sql_runs=sql_runs,
            review_insights=review_insights,
        )
        return heuristic.model_copy(
            update={
                "reasoning": (
                    f"LLM 结构化输出失败，已回退规则：{exc}；{heuristic.reasoning}"
                )
            }
        )
