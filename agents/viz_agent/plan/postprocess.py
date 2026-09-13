"""套件任务规则后处理：补漏图、拆多 SQL、去 KPI、预测折线、诊断评论图、去重。"""

from __future__ import annotations

from typing import Any

from agents.viz_agent.plan.columns import (
    _cols_for_sql_run,
    _has_text_column,
    _is_scalar_kpi_result,
    _result_columns,
    _sql_result_rows_from_payload,
    _sql_run_payload,
    _summarize_sql_runs,
)
from agents.viz_agent.plan.line_plan import column_is_category, column_is_time
from agents.viz_agent.plan.tasks import (
    ChartHint,
    VizChartTask,
    _REASON_COLUMN_HINTS,
    _REASON_QUESTION_HINTS,
    _REVIEW_VIZ_HINTS,
)

_GLOBAL_COMPARE_WC_FP = "wordcloud:compare:global"
_GMV_PREDICTIVE_HINTS = ("销售额", "gmv", "销售", "营收", "营业额")
_FORECAST_QUERY_HINTS = ("预测", "未来", "6周", "六周", "外推")


def _infer_hint_from_columns(cols: list[str], question: str) -> ChartHint:
    cl = [c.lower() for c in cols]
    ql = (question or "").lower()
    if any("lat" in c for c in cl) and any("lng" in c or "lon" in c for c in cl):
        return "geo_scatter"
    if _has_text_column(cols) and any(k in ql for k in ("词云", "评论", "review")):
        return "wordcloud"
    if any(k in ql for k in ("热力", "矩阵", "交叉")):
        return "heatmap"
    has_time = any(column_is_time(c) for c in cols)
    has_category = any(column_is_category(c) for c in cols)
    if has_time and has_category:
        return "line"
    if has_category and not has_time:
        return "bar"
    if has_time or any(k in ql for k in ("预测", "未来", "forecast", "趋势", "走势", "按月")):
        return "line"
    if has_category and any(k in ql for k in ("排名", "对比", "top", "各州")):
        return "bar"
    if len(cols) >= 3:
        return "bar"
    return "auto"


def _infer_hint_for_sql_result(row: dict[str, Any], question: str) -> ChartHint:
    cols = _result_columns(row)
    hint = _infer_hint_from_columns(cols, question)
    if hint != "auto":
        return hint
    row_count = int(row.get("row_count_returned") or 0)
    if row_count > 1 and any(column_is_category(c) for c in cols):
        if any(column_is_time(c) for c in cols):
            return "line"
        return "bar"
    return "auto"


def chart_task_fingerprint(
    chart: VizChartTask,
    *,
    sql_runs: list[dict[str, Any]] | None = None,
) -> str:
    """规划阶段指纹：仅当图表类型 + 取数来源 + 数据结构一致时视为重复。"""
    if chart.data_source == "wordcloud":
        return _GLOBAL_COMPARE_WC_FP
    if chart.data_source == "review_insights" and chart.insight_chart_type:
        return f"review_insights:{chart.insight_chart_type}"
    if chart.data_source == "sql_run":
        idx = chart.sql_run_index if chart.sql_run_index is not None else -1
        res_idx = chart.sql_result_index if chart.sql_result_index is not None else -1
        hint = chart.chart_type_hint or "auto"
        cols = ",".join(sorted(_cols_for_sql_run(sql_runs, idx)))
        return f"sql_run:{idx}:{res_idx}:{hint}:{cols}"
    if chart.data_source == "supplementary_query":
        q = (chart.supplementary_question or chart.title or "").strip()
        hint = chart.chart_type_hint or "auto"
        return f"supplementary:{q}:{hint}"
    return f"other:{chart.data_source}:{chart.title}"


def _normalize_chart_tasks(
    charts: list[VizChartTask],
    *,
    sql_runs: list[dict[str, Any]] | None = None,
) -> list[VizChartTask]:
    """无文本列的 SQL 结果被误标 wordcloud 时改为柱状图；有文本列则保留单词云。"""
    out: list[VizChartTask] = []
    for chart in charts:
        if chart.data_source == "sql_run" and chart.chart_type_hint == "wordcloud":
            cols = _cols_for_sql_run(sql_runs, chart.sql_run_index)
            if cols and not _has_text_column(cols):
                out.append(chart.model_copy(update={"chart_type_hint": "bar"}))
            else:
                out.append(chart)
        else:
            out.append(chart)
    return out


def _dominant_topic(topic_distribution: dict[str, int]) -> str | None:
    if not topic_distribution:
        return None
    return max(topic_distribution, key=lambda k: int(topic_distribution[k] or 0))


def _has_global_compare_wordcloud(charts: list[VizChartTask]) -> bool:
    """是否已有 data_source=wordcloud 的全库好评/差评对比词云任务。"""
    return any(c.data_source == "wordcloud" for c in charts)


def _dedupe_viz_charts(
    charts: list[VizChartTask],
    *,
    sql_runs: list[dict[str, Any]] | None = None,
) -> list[VizChartTask]:
    """去掉规划阶段可判定为类型+内容完全相同的重复任务。"""
    out: list[VizChartTask] = []
    seen: set[str] = set()
    for chart in charts:
        fp = chart_task_fingerprint(chart, sql_runs=sql_runs)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(chart)
    return out


def _is_gmv_predictive_query(user_query: str, intent: str) -> bool:
    if intent != "predictive":
        return False
    q = (user_query or "").lower()
    return any(h in user_query or h in q for h in _FORECAST_QUERY_HINTS) and any(
        h in user_query or h in q for h in _GMV_PREDICTIVE_HINTS
    )


def _is_placeholder_forecast_sql_run(run: dict[str, Any]) -> bool:
    """SQL Agent 对未来预测生成的 NULL 占位结果，不可制图。"""
    summary = _summarize_sql_runs([run])[0]
    cols = [c.lower() for c in summary.get("columns") or []]
    if any("forecast" in c for c in cols):
        return True
    ar = run.get("analysis_result") or {}
    text = str(ar.get("business_summary") or "")
    if "占位" in text or ("NULL" in text and "预测" in text):
        return True
    return False


def _sql_run_has_monthly_gmv(sql_runs: list[dict[str, Any]], index: int) -> bool:
    cols = [c.lower() for c in _cols_for_sql_run(sql_runs, index)]
    has_time = any(column_is_time(c) for c in cols)
    has_gmv = any(
        any(k in c for k in ("gmv", "sales", "total_gmv", "gmv_total"))
        for c in cols
    )
    return has_time and has_gmv


def _enrich_gmv_predictive_charts(
    *,
    user_query: str,
    intent: str,
    charts: list[VizChartTask],
    sql_runs: list[dict[str, Any]],
) -> list[VizChartTask]:
    """销售额预测：确保有一张带 6 周外推叠加的月度 GMV 折线图。"""
    if not _is_gmv_predictive_query(user_query, intent):
        return charts

    out: list[VizChartTask] = []
    forecast_assigned = False
    for chart in charts:
        if (
            chart.data_source == "sql_run"
            and chart.chart_type_hint == "line"
            and chart.sql_run_index is not None
            and _sql_run_has_monthly_gmv(sql_runs, chart.sql_run_index)
            and not forecast_assigned
        ):
            out.append(
                chart.model_copy(
                    update={
                        "include_forecast": True,
                        "title": "历史月度 GMV 与未来 6 周预测",
                        "rationale": "历史 mv_monthly_sales 趋势叠加周度 GMV 线性外推",
                    }
                )
            )
            forecast_assigned = True
        else:
            out.append(chart)

    if forecast_assigned:
        return out

    for i, run in enumerate(sql_runs):
        if _is_placeholder_forecast_sql_run(run):
            continue
        if not _sql_run_has_monthly_gmv(sql_runs, i):
            continue
        out.append(
            VizChartTask(
                title="历史月度 GMV 与未来 6 周预测",
                rationale="基于 mv_monthly_sales 历史趋势叠加周度外推",
                data_source="sql_run",
                sql_run_index=i,
                chart_type_hint="line",
                include_forecast=True,
            )
        )
        break
    return out or charts


def _chart_targets_scalar_sql_run(
    chart: VizChartTask,
    *,
    sql_runs: list[dict[str, Any]],
) -> bool:
    if chart.data_source != "sql_run" or chart.sql_run_index is None:
        return False
    payload = _sql_run_payload(sql_runs, chart.sql_run_index)
    if not payload:
        return False
    rows = _sql_result_rows_from_payload(payload)
    if not rows:
        return False
    if chart.sql_result_index is not None:
        if chart.sql_result_index < 0 or chart.sql_result_index >= len(rows):
            return False
        return _is_scalar_kpi_result(rows[chart.sql_result_index])
    if len(rows) == 1:
        return _is_scalar_kpi_result(rows[0])
    return False


def _filter_scalar_sql_chart_tasks(
    charts: list[VizChartTask],
    *,
    sql_runs: list[dict[str, Any]],
) -> list[VizChartTask]:
    """单行单一汇总指标已在文字答复中呈现，无需强行出图。"""
    return [
        chart
        for chart in charts
        if not _chart_targets_scalar_sql_run(chart, sql_runs=sql_runs)
    ]


def _sql_run_indices_covered(charts: list[VizChartTask]) -> set[int]:
    return {
        int(c.sql_run_index)
        for c in charts
        if c.data_source == "sql_run" and c.sql_run_index is not None
    }


def _expand_multi_result_sql_tasks(
    charts: list[VizChartTask],
    *,
    sql_runs: list[dict[str, Any]],
    user_query: str,
    intent: str,
) -> list[VizChartTask]:
    """同一 sql_run 含多条 SQL 结果（如排名 + 趋势）时，为每条可制图结果补齐任务。"""
    out = list(charts)
    include_fc = intent == "predictive" or any(
        k in user_query for k in ("预测", "未来", "6周", "六周")
    )
    existing: set[tuple[int, int]] = {
        (int(c.sql_run_index), int(c.sql_result_index))
        for c in out
        if c.data_source == "sql_run"
        and c.sql_run_index is not None
        and c.sql_result_index is not None
    }
    covered_runs = _sql_run_indices_covered(out)

    for i, run in enumerate(sql_runs):
        if _is_placeholder_forecast_sql_run(run):
            continue
        payload = _sql_run_payload(sql_runs, i)
        if not payload:
            continue
        rows = _sql_result_rows_from_payload(payload)
        if len(rows) <= 1:
            continue
        question = str(run.get("question") or user_query)
        for j, row in enumerate(rows):
            if _is_scalar_kpi_result(row):
                continue
            if (i, j) in existing:
                continue
            hint = _infer_hint_for_sql_result(row, question)
            title_suffix = "排名" if hint == "bar" and j == 0 else ""
            base_title = question.rstrip("？")
            if title_suffix and title_suffix not in base_title:
                title = f"{base_title}（{title_suffix}）"
            else:
                title = base_title
            out.append(
                VizChartTask(
                    title=title,
                    rationale=f"基于子问题「{question}」第 {j + 1} 条查数结果可视化",
                    data_source="sql_run",
                    sql_run_index=i,
                    sql_result_index=j,
                    chart_type_hint=hint,
                    include_forecast=include_fc and hint == "line",
                )
            )
            existing.add((i, j))
            covered_runs.add(i)
    return out


def _question_expects_reason_viz(question: str) -> bool:
    return any(k in question for k in _REASON_QUESTION_HINTS)


def _columns_support_reason_viz(cols: list[str]) -> bool:
    return _has_text_column(cols) or any(
        any(h in c.lower() for h in _REASON_COLUMN_HINTS) for c in cols
    )


def _ensure_sql_run_chart_tasks(
    charts: list[VizChartTask],
    *,
    sql_runs: list[dict[str, Any]],
    user_query: str,
    intent: str,
) -> list[VizChartTask]:
    """每条已成功查数的 sql_run 至少规划一张图（LLM 漏规划时补齐）。"""
    out = list(charts)
    covered = _sql_run_indices_covered(out)
    include_fc = intent == "predictive" or any(
        k in user_query for k in ("预测", "未来", "6周", "六周")
    )
    for i, run in enumerate(sql_runs):
        if i in covered:
            continue
        if _is_placeholder_forecast_sql_run(run):
            continue
        summary = _summarize_sql_runs([run])[0]
        if not summary.get("ok") or not summary.get("columns"):
            continue
        cols = summary["columns"]
        question = str(run.get("question") or user_query)
        if _question_expects_reason_viz(question) and not _columns_support_reason_viz(
            cols
        ):
            continue
        payload = _sql_run_payload(sql_runs, i)
        if payload:
            rows = _sql_result_rows_from_payload(payload)
            if rows and all(_is_scalar_kpi_result(r) for r in rows):
                continue
            if len(rows) > 1:
                continue
        hint = _infer_hint_from_columns(cols, question)
        out.append(
            VizChartTask(
                title=question.rstrip("？"),
                rationale=f"基于子问题「{question}」的查数结果可视化",
                data_source="sql_run",
                sql_run_index=i,
                chart_type_hint=hint,
                include_forecast=include_fc and hint == "line",
            )
        )
    return out


def _finalize_sql_chart_tasks(
    charts: list[VizChartTask],
    *,
    sql_runs: list[dict[str, Any]],
    user_query: str,
    intent: str,
) -> list[VizChartTask]:
    """LLM/启发式任务的规则后处理：补齐漏掉的 sql_run、拆多 SQL 结果、丢掉单值 KPI、预测折线叠外推。"""
    charts = _normalize_chart_tasks(charts, sql_runs=sql_runs)
    charts = _ensure_sql_run_chart_tasks(
        charts,
        sql_runs=sql_runs,
        user_query=user_query,
        intent=intent,
    )
    charts = _expand_multi_result_sql_tasks(
        charts,
        sql_runs=sql_runs,
        user_query=user_query,
        intent=intent,
    )
    charts = _filter_scalar_sql_chart_tasks(charts, sql_runs=sql_runs)
    charts = _enrich_gmv_predictive_charts(
        user_query=user_query,
        intent=intent,
        charts=charts,
        sql_runs=sql_runs,
    )
    return charts


def _insight_data_available(
    review_insights: dict[str, Any] | None, kind: str
) -> bool:
    from agents.viz_agent.data.insight_charts import insight_chart_has_data

    return insight_chart_has_data(review_insights, kind)


def _strip_unrenderable_insight_charts(
    charts: list[VizChartTask],
    review_insights: dict[str, Any] | None,
) -> list[VizChartTask]:
    """去掉 NLP 数据为空、必然渲染失败的 review_insights 任务。"""
    out: list[VizChartTask] = []
    for chart in charts:
        if chart.data_source != "review_insights" or not chart.insight_chart_type:
            out.append(chart)
            continue
        if _insight_data_available(review_insights, chart.insight_chart_type):
            out.append(chart)
    return out


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
    sql_runs: list[dict[str, Any]] | None = None,
) -> list[VizChartTask]:
    """差评/原因类诊断问题：基于 NLP 洞察主动追加佐证图。"""
    insights = review_insights or {}
    out = list(charts)
    titles = {c.title for c in out}

    if _insight_data_available(insights, "topic_distribution") and not any(
        "主题分布" in t for t in titles
    ):
        out.append(
            VizChartTask(
                title="差评主题分布（佐证原因分析）",
                rationale="回答「主要差评原因」，展示配送/价格/质量等主题占比",
                data_source="review_insights",
                chart_type_hint="bar",
                insight_chart_type="topic_distribution",
            )
        )

    if _insight_data_available(insights, "complaints_by_category") and not any(
        "主题矩阵" in t or "×" in t for t in titles
    ):
        out.append(
            VizChartTask(
                title="Top差评品类 × 差评主题矩阵",
                rationale="展示各差评品类的主导抱怨主题，支撑原因诊断",
                data_source="review_insights",
                chart_type_hint="heatmap",
                insight_chart_type="complaints_by_category",
            )
        )

    if any(k in user_query for k in ("评论", "差评", "词云", "口碑")) and not _has_global_compare_wordcloud(
        out
    ):
        out.append(
            VizChartTask(
                title="好评 vs 差评 评论词云对比",
                rationale="从评论文本直观对比正负反馈用词",
                data_source="wordcloud",
                chart_type_hint="wordcloud",
            )
        )

    td = insights.get("topic_distribution") or {}
    top_topic = _dominant_topic({k: int(v) for k, v in td.items()})
    if top_topic:
        extra = _supplementary_for_topic(top_topic)
        if extra and extra.title not in titles:
            out.append(extra)

    return _dedupe_viz_charts(out, sql_runs=sql_runs)
