"""根据用户问题与 SQL 分析结果，规划需要生成的图表套件。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

DataSource = Literal["sql_run", "supplementary_query", "wordcloud", "review_insights"]
InsightChartType = Literal["topic_distribution", "complaints_by_category"]
ChartHint = Literal[
    "line", "bar", "heatmap", "scatter", "geo_scatter", "wordcloud", "auto"
]


class VizChartTask(BaseModel):
    title: str = Field(description="图表标题")
    rationale: str = Field(default="", description="此图如何服务用户问题")
    data_source: DataSource
    sql_run_index: int | None = None
    supplementary_question: str | None = None
    chart_type_hint: ChartHint = "auto"
    include_forecast: bool = False
    insight_chart_type: InsightChartType | None = None


class VizSuitePlan(BaseModel):
    needs_visualization: bool = False
    reasoning: str = ""
    charts: list[VizChartTask] = Field(default_factory=list)

    @field_validator("charts")
    @classmethod
    def _validate_tasks(cls, charts: list[VizChartTask]) -> list[VizChartTask]:
        return charts


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_suite_prompt() -> str:
    return (_project_root() / "config" / "visualization_agent" / "plan_suite.md").read_text(
        encoding="utf-8"
    )


def _extract_json_object(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


_VIZ_HINTS = (
    "趋势",
    "走势",
    "分布",
    "对比",
    "排名",
    "各州",
    "各月",
    "品类",
    "可视化",
    "图表",
    "图",
    "热力",
    "地理",
    "预测",
    "词云",
    "top",
    "最高",
    "最低",
    "占比",
    "结构",
)
_COMPREHENSIVE_HINTS = ("整体", "全面", "运营状况", "综合分析", "多维度", "概况")
_REVIEW_VIZ_HINTS = ("差评", "原因", "投诉", "抱怨", "评论", "口碑", "主题", "词云")

_TOPIC_ZH: dict[str, str] = {
    "delivery_delay": "配送延迟",
    "not_received": "未收到货",
    "product_quality": "商品质量",
    "wrong_item": "发错货",
    "customer_service": "客服问题",
    "price_freight": "价格/运费",
    "missing_parts": "缺件/不完整",
    "other": "其他",
}


def query_suggests_visualization(user_query: str, intent: str) -> bool:
    q = user_query or ""
    ql = q.lower()
    if intent in ("predictive", "diagnostic"):
        return True
    if any(h in q or h in ql for h in _REVIEW_VIZ_HINTS):
        return True
    if any(h in q or h in ql for h in _COMPREHENSIVE_HINTS):
        return True
    return any(h in q or h in ql for h in _VIZ_HINTS)


def _summarize_sql_runs(sql_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for i, run in enumerate(sql_runs):
        ar = run.get("analysis_result") or {}
        exec_json = run.get("execute_sql_json") or ""
        cols: list[str] = []
        row_count = 0
        summary_zh = ""
        ok = False
        if exec_json.strip():
            try:
                payload = json.loads(exec_json)
                ok = bool(payload.get("ok"))
                summary_zh = str(payload.get("data_summary_zh") or "")
                profiles = payload.get("column_profiles") or []
                cols = [str(p.get("name")) for p in profiles if p.get("name")]
                row_count = int(payload.get("row_count_returned") or 0)
            except json.JSONDecodeError:
                pass
        summaries.append(
            {
                "index": i,
                "question": run.get("question"),
                "ok": ok,
                "business_summary": ar.get("business_summary"),
                "data_summary_zh": summary_zh,
                "columns": cols,
                "row_count": row_count,
                "views_used": (ar.get("sql_meta") or {}).get("candidate_views"),
            }
        )
    return summaries


def _build_planner_context(
    *,
    user_query: str,
    intent: str,
    sql_runs: list[dict[str, Any]],
    review_insights: dict[str, Any] | None = None,
) -> str:
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


def _infer_hint_from_columns(cols: list[str], question: str) -> ChartHint:
    cl = [c.lower() for c in cols]
    ql = (question or "").lower()
    if any("lat" in c for c in cl) and any("lng" in c or "lon" in c for c in cl):
        return "geo_scatter"
    if any(k in ql for k in ("词云", "评论", "差评", "review")):
        return "wordcloud"
    if any(k in ql for k in ("热力", "矩阵", "交叉")):
        return "heatmap"
    if any(k in c for c in cl for k in ("month", "year", "date", "timestamp")):
        return "line"
    if any(k in ql for k in ("预测", "未来", "forecast")):
        return "line"
    if len(cols) >= 3:
        return "bar"
    return "auto"


def _dominant_topic(topic_distribution: dict[str, int]) -> str | None:
    if not topic_distribution:
        return None
    return max(topic_distribution, key=lambda k: int(topic_distribution[k] or 0))


def _supplementary_for_topic(topic_key: str) -> VizChartTask | None:
    if topic_key == "price_freight":
        return VizChartTask(
            title="Top差评品类平均售价对比（佐证价格原因）",
            rationale="价格/运费是主要差评主题，用品类均价对比佐证",
            data_source="supplementary_query",
            supplementary_question=(
                "查询差评相关 Top10 品类的平均商品售价（avg_price），"
                "按均价降序排列，用于分析价格类差评。"
            ),
            chart_type_hint="bar",
        )
    if topic_key == "delivery_delay":
        return VizChartTask(
            title="Top差评品类所属州的平均配送天数（佐证延迟原因）",
            rationale="配送延迟是主要差评主题，用配送绩效佐证",
            data_source="supplementary_query",
            supplementary_question=(
                "查询差评率较高的 Top10 品类对应订单的平均配送天数（avg_delivery_days），"
                "按配送天数降序排列。"
            ),
            chart_type_hint="bar",
        )
    if topic_key == "product_quality":
        return VizChartTask(
            title="Top差评品类平均评分对比（佐证质量原因）",
            rationale="商品质量是主要差评主题，用评分对比佐证",
            data_source="supplementary_query",
            supplementary_question=(
                "查询差评 Top10 品类的平均 review_score，按评分升序排列。"
            ),
            chart_type_hint="bar",
        )
    return None


def _enrich_diagnostic_review_charts(
    *,
    user_query: str,
    charts: list[VizChartTask],
    review_insights: dict[str, Any] | None,
) -> list[VizChartTask]:
    """差评/原因类诊断问题：基于 NLP 洞察主动追加佐证图。"""
    insights = review_insights or {}
    out = list(charts)
    titles = {c.title for c in out}

    td = insights.get("topic_distribution") or {}
    if td and not any("主题分布" in t for t in titles):
        out.append(
            VizChartTask(
                title="差评主题分布（佐证原因分析）",
                rationale="回答「主要差评原因」，展示配送/价格/质量等主题占比",
                data_source="review_insights",
                chart_type_hint="bar",
                insight_chart_type="topic_distribution",
            )
        )

    cbc = insights.get("complaints_by_category") or []
    if cbc and not any("主题矩阵" in t or "×" in t for t in titles):
        out.append(
            VizChartTask(
                title="Top差评品类 × 差评主题矩阵",
                rationale="展示各差评品类的主导抱怨主题，支撑原因诊断",
                data_source="review_insights",
                chart_type_hint="heatmap",
                insight_chart_type="complaints_by_category",
            )
        )

    if any(k in user_query for k in ("评论", "差评", "词云", "口碑")) and not any(
        "词云" in t for t in titles
    ):
        out.append(
            VizChartTask(
                title="好评 vs 差评 评论词云对比",
                rationale="从评论文本直观对比正负反馈用词",
                data_source="wordcloud",
                chart_type_hint="wordcloud",
            )
        )

    top_topic = _dominant_topic({k: int(v) for k, v in td.items()})
    if top_topic:
        extra = _supplementary_for_topic(top_topic)
        if extra and extra.title not in titles:
            out.append(extra)

    return out


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

    if any(k in user_query for k in ("评论", "差评", "词云", "口碑", "review")):
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
        )

    if not charts:
        return VizSuitePlan(
            needs_visualization=False,
            reasoning="SQL 结果不可用或不适合制图。",
        )

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
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.decision_agent.llm import get_llm

    llm = model or get_llm()
    system = _load_suite_prompt()
    human = (
        f"【用户问题】\n{user_query}\n\n"
        f"【intent】\n{intent}\n\n"
        f"【已完成分析】\n{_build_planner_context(user_query=user_query, intent=intent, sql_runs=sql_runs, review_insights=review_insights)}\n\n"
        "请输出 JSON。"
    )
    resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
    raw = _extract_json_object(str(resp.content))
    plan = VizSuitePlan.model_validate_json(raw)
    if (intent == "diagnostic" or any(k in user_query for k in _REVIEW_VIZ_HINTS)) and plan.charts:
        plan = plan.model_copy(
            update={
                "charts": _enrich_diagnostic_review_charts(
                    user_query=user_query,
                    charts=plan.charts,
                    review_insights=review_insights,
                )
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
    use_llm: bool = True,
) -> VizSuitePlan:
    if not query_suggests_visualization(user_query, intent) and intent not in ("predictive",):
        return VizSuitePlan(
            needs_visualization=False,
            reasoning="问题未体现可视化需求，跳过出图。",
        )
    if use_llm:
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
        except Exception:
            pass
    return heuristic_viz_suite(
        user_query=user_query,
        intent=intent,
        sql_runs=sql_runs,
        review_insights=review_insights,
    )
