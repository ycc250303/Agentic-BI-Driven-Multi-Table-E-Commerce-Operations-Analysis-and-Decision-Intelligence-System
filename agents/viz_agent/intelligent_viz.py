"""
智能可视化执行：先规划「需要什么图、从哪取数」，再按需查数/复用 SQL 结果并渲染。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.coordinator_agent.adapters import (
    build_viz_execute_json,
    merge_visualization_results,
    pick_viz_csv_from_exec_payload,
)
from agents.viz_agent.forecast import forecast_weekly_gmv
from agents.viz_agent.render import render_to_png
from agents.viz_agent.render_context import RenderExtras
from agents.viz_agent.schema import VisualizationAgentOutput, VizPlan
from agents.viz_agent.viz_planner import VizChartTask, VizSuitePlan, plan_viz_suite

_viz_dir = Path(__file__).resolve().parent
_project_root = _viz_dir.parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _normalize_viz_plan(plan: VizPlan | dict[str, Any]) -> VizPlan:
    """避免 viz_agent.run 与包路径重复加载 schema 导致 Pydantic 类型不一致。"""
    if isinstance(plan, VizPlan):
        return plan
    return VizPlan.model_validate(plan)


def _viz_output(**kwargs: Any) -> dict[str, Any]:
    plan = kwargs.get("plan")
    if plan is not None:
        kwargs["plan"] = _normalize_viz_plan(plan)
    return VisualizationAgentOutput(**kwargs).model_dump()


def _viz_output_dir() -> Path:
    import os

    raw = os.environ.get("AGENTIC_BI_VIZ_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (_viz_dir / "chart_output").resolve()


def _load_sql_pipeline():
    import importlib.util

    sql_dir = _viz_dir.parent / "sql_agent"
    run_path = sql_dir / "run.py"
    if str(sql_dir) not in sys.path:
        sys.path.insert(0, str(sql_dir))
    spec = importlib.util.spec_from_file_location("agentic_bi_sql_agent_run", run_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 SQL Agent：{run_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_sql_pipeline_with_feedback


def _run_viz_from_exec_payload(
    *,
    user_query: str,
    exec_payload: dict[str, Any],
    chart_task: VizChartTask,
    model=None,
    use_llm: bool = True,
) -> dict[str, Any]:
    from agents.viz_agent.run import heuristic_plan, plan_with_llm, run_visualization_agent

    csv_path = pick_viz_csv_from_exec_payload(exec_payload)
    if not csv_path:
        return _viz_output(
            ok=False,
            error_message="无可用 CSV",
            user_query=user_query,
        )

    row = next(
        (
            r
            for r in (exec_payload.get("results") or [])
            if r.get("ok") and str(r.get("result_csv_path")) == csv_path
        ),
        {"result_csv_path": csv_path, "data_summary_zh": exec_payload.get("data_summary_zh")},
    )
    exec_json = build_viz_execute_json(exec_payload, row)

    hint = chart_task.chart_type_hint
    if hint and hint != "auto" and use_llm:
        import pandas as pd

        payload = json.loads(exec_json)
        df = pd.read_csv(csv_path)
        profiles = payload.get("column_profiles") or []
        summary = str(payload.get("data_summary_zh") or "")
        viz_query = f"{chart_task.title}。{chart_task.rationale}。倾向图表类型：{hint}"
        try:
            plan, plan_raw = plan_with_llm(
                viz_query, df, profiles, summary, model=model
            )
            if hint != "auto" and plan.chart_type != hint:
                plan = plan.model_copy(
                    update={"chart_type": hint, "title": chart_task.title or plan.title}
                )
        except Exception:
            plan = heuristic_plan(df, viz_query)
            plan_raw = plan.model_dump_json()
        plan = _normalize_viz_plan(plan)
        return _render_with_plan(
            df=df,
            plan=plan,
            plan_raw=plan_raw,
            user_query=viz_query,
            csv_path=str(Path(csv_path).resolve()),
            chart_task=chart_task,
        )

    out = run_visualization_agent(
        user_query=f"{chart_task.title}。{chart_task.rationale}",
        execute_sql_json=exec_json,
        model=model,
        use_llm=use_llm,
    )
    if out.get("ok") and chart_task.include_forecast:
        out = _maybe_apply_forecast_overlay(out, chart_task)
    return out


def _allocate_png_path(
    out_dir: Path, chart_type: str, chart_task: VizChartTask | None = None
) -> Path:
    """带 sql_run / 洞察类型 标签的文件名，避免同秒多张 bar 图难以区分。"""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    tag = ""
    if chart_task is not None:
        if chart_task.data_source == "sql_run" and chart_task.sql_run_index is not None:
            tag = f"_sql{chart_task.sql_run_index}"
        elif chart_task.data_source == "wordcloud":
            tag = "_wc"
        elif (
            chart_task.data_source == "review_insights"
            and chart_task.insight_chart_type
        ):
            tag = f"_{chart_task.insight_chart_type}"
    stem = f"viz_{chart_type}{tag}_{ts}"
    path = out_dir / f"{stem}.png"
    n = 1
    while path.exists():
        path = out_dir / f"{stem}_{n}.png"
        n += 1
    return path


def _render_with_plan(
    *,
    df,
    plan: VizPlan,
    plan_raw: str,
    user_query: str,
    csv_path: str,
    chart_task: VizChartTask,
) -> dict[str, Any]:
    plan = _normalize_viz_plan(plan)
    out_dir = _viz_output_dir()
    png_path = _allocate_png_path(out_dir, plan.chart_type, chart_task)
    extras = _build_render_extras(chart_task, plan)
    try:
        img = render_to_png(df, plan, png_path, extras=extras)
    except Exception as e:
        return _viz_output(
            ok=False,
            error_message=f"渲染失败：{e}",
            user_query=user_query,
            csv_path=csv_path,
            plan=plan,
            plan_raw_json=plan_raw,
            chart_type_resolved=plan.chart_type,
        )
    result = _viz_output(
        ok=True,
        user_query=user_query,
        csv_path=csv_path,
        plan=plan,
        plan_raw_json=plan_raw,
        image_path=img,
        chart_type_resolved=plan.chart_type,
    )
    if extras and extras.forecast and extras.forecast.get("ok"):
        result["forecast_summary"] = extras.forecast.get("summary_text")
    return result


def _build_render_extras(chart_task: VizChartTask, plan: VizPlan) -> RenderExtras | None:
    # rationale 仅供规划/LLM，不渲染到图上（避免提示词式长文破坏观感）
    subtitle = ""
    if plan.chart_type == "wordcloud":
        subtitle = "左：好评(≥4分)  右：差评(≤2分)"
    extras = RenderExtras(subtitle=subtitle)
    if chart_task.include_forecast and plan.chart_type == "line":
        fc = forecast_weekly_gmv(horizon_weeks=6)
        if fc.get("ok"):
            extras.forecast = fc
    if plan.chart_type == "geo_scatter":
        extras.color_column = plan.hue_column or "total_gmv"
    if plan.chart_type == "bar":
        extras.value_format = "currency" if any(
            k in (plan.y_column or "").lower() for k in ("gmv", "sales", "basket", "value")
        ) else "auto"
    return extras


def _maybe_apply_forecast_overlay(out: dict[str, Any], chart_task: VizChartTask) -> dict[str, Any]:
    if not chart_task.include_forecast or not out.get("ok"):
        return out
    plan_dict = out.get("plan") or {}
    if plan_dict.get("chart_type") != "line":
        return out
    import pandas as pd

    csv_path = out.get("csv_path")
    if not csv_path:
        return out
    try:
        df = pd.read_csv(csv_path)
        plan = VizPlan.model_validate(plan_dict)
        png_path = Path(str(out.get("image_path") or ""))
        if not png_path.name:
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            png_path = _viz_output_dir() / f"viz_line_fc_{ts}.png"
        extras = _build_render_extras(chart_task, plan)
        img = render_to_png(df, plan, png_path, extras=extras)
        out["image_path"] = img
        if extras and extras.forecast and extras.forecast.get("ok"):
            out["forecast_summary"] = extras.forecast.get("summary_text")
    except Exception:
        pass
    return out


def _render_wordcloud_task(
    chart_task: VizChartTask,
    review_insights: dict[str, Any] | None,
) -> dict[str, Any]:
    from agents.nlp_agent.tools.wordcloud_data import run_wordcloud_data

    wc_data = (review_insights or {}).get("wordcloud")
    if not wc_data or not (wc_data.get("positive") or wc_data.get("negative")):
        try:
            wc_data = run_wordcloud_data(top_n=80, pos_sample=4000, neg_sample=4000)
        except Exception as e:
            return _viz_output(
                ok=False,
                error_message=f"词云数据获取失败：{e}",
                user_query=chart_task.title,
                chart_type_resolved="wordcloud",
            )

    plan = VizPlan(
        chart_type="wordcloud",
        title=chart_task.title,
        reasoning=chart_task.rationale,
    )
    out_dir = _viz_output_dir()
    png_path = _allocate_png_path(out_dir, "wordcloud", chart_task)
    extras = RenderExtras(
        wordcloud_compare={
            "positive": wc_data.get("positive") or {},
            "negative": wc_data.get("negative") or {},
        },
        subtitle="左：好评(≥4分)  右：差评(≤2分)",
    )
    try:
        import pandas as pd

        img = render_to_png(pd.DataFrame(), plan, png_path, extras=extras)
    except Exception as e:
        return _viz_output(
            ok=False,
            error_message=f"词云渲染失败：{e}",
            user_query=chart_task.title,
            plan=plan,
            chart_type_resolved="wordcloud",
        )
    return _viz_output(
        ok=True,
        user_query=chart_task.title,
        plan=plan,
        plan_raw_json=plan.model_dump_json(),
        image_path=img,
        chart_type_resolved="wordcloud",
    )


def _insights_to_dataframe(insights: dict[str, Any], kind: str):
    import pandas as pd

    from agents.viz_agent.insight_charts import insight_chart_rows

    return pd.DataFrame(insight_chart_rows(insights, kind))


def _render_review_insights_task(
    chart_task: VizChartTask,
    review_insights: dict[str, Any] | None,
) -> dict[str, Any]:
    insights = review_insights or {}
    kind = chart_task.insight_chart_type
    if not kind:
        return _viz_output(
            ok=False,
            error_message="review_insights 任务缺少 insight_chart_type",
            user_query=chart_task.title,
        )

    df = _insights_to_dataframe(insights, kind)
    if df.empty:
        return _viz_output(
            ok=False,
            error_message="NLP 洞察数据为空，无法渲染佐证图",
            user_query=chart_task.title,
        )

    if kind == "topic_distribution":
        plan = VizPlan(
            chart_type="bar",
            title=chart_task.title,
            x_column="topic",
            y_column="count",
            reasoning=chart_task.rationale,
        )
    else:
        plan = VizPlan(
            chart_type="heatmap",
            title=chart_task.title,
            pivot_row_col="category",
            pivot_col_col="topic",
            pivot_value_col="count",
            reasoning=chart_task.rationale,
        )

    return _render_with_plan(
        df=df,
        plan=plan,
        plan_raw=plan.model_dump_json(),
        user_query=chart_task.title,
        csv_path="",
        chart_task=chart_task,
    )


def _execute_chart_task(
    chart_task: VizChartTask,
    *,
    sql_runs: list[dict[str, Any]],
    review_insights: dict[str, Any] | None,
    model=None,
    use_llm: bool = True,
    on_tool_end: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    if chart_task.data_source == "wordcloud":
        item = _render_wordcloud_task(chart_task, review_insights)
        item["task_title"] = chart_task.title
        item["task_rationale"] = chart_task.rationale
        return item

    if chart_task.data_source == "sql_run":
        idx = chart_task.sql_run_index
        if idx is None or idx < 0 or idx >= len(sql_runs):
            return _viz_output(
                ok=False,
                error_message=f"无效的 sql_run_index={idx}",
                user_query=chart_task.title,
            )
        run = sql_runs[idx]
        exec_json = run.get("execute_sql_json") or ""
        try:
            exec_payload = json.loads(exec_json)
        except json.JSONDecodeError:
            return _viz_output(
                ok=False,
                error_message="SQL 结果 JSON 解析失败",
                user_query=chart_task.title,
            )
        item = _run_viz_from_exec_payload(
            user_query=str(run.get("question") or chart_task.title),
            exec_payload=exec_payload,
            chart_task=chart_task,
            model=model,
            use_llm=use_llm,
        )
        item["task_title"] = chart_task.title
        item["task_rationale"] = chart_task.rationale
        item["sql_run_index"] = idx
        return item

    if chart_task.data_source == "review_insights":
        item = _render_review_insights_task(chart_task, review_insights)
        item["task_title"] = chart_task.title
        item["task_rationale"] = chart_task.rationale
        return item

    if chart_task.data_source == "supplementary_query":
        question = (chart_task.supplementary_question or chart_task.title).strip()
        if not question:
            return _viz_output(
                ok=False,
                error_message="supplementary_query 缺少问题文本",
                user_query=chart_task.title,
            )
        run_sql = _load_sql_pipeline()
        sql_out = run_sql(question, model=model, on_tool_end=on_tool_end)
        try:
            exec_payload = json.loads(sql_out.get("execute_sql_json") or "{}")
        except json.JSONDecodeError:
            exec_payload = {}
        if not exec_payload.get("ok"):
            return _viz_output(
                ok=False,
                error_message=exec_payload.get("error_message")
                or f"补充查数失败：{question}",
                user_query=chart_task.title,
            )
        item = _run_viz_from_exec_payload(
            user_query=question,
            exec_payload=exec_payload,
            chart_task=chart_task,
            model=model,
            use_llm=use_llm,
        )
        item["task_title"] = chart_task.title
        item["task_rationale"] = chart_task.rationale
        item["supplementary_query"] = question
        return item

    return _viz_output(
        ok=False,
        error_message=f"未知 data_source：{chart_task.data_source}",
        user_query=chart_task.title,
    )


def rendered_chart_fingerprint(item: dict[str, Any], task: VizChartTask) -> str | None:
    """渲染完成后按「图表类型 + 实际数据」生成指纹，用于剔除画面完全相同的图。"""
    if not item.get("ok"):
        return None
    plan_raw = item.get("plan") or {}
    if isinstance(plan_raw, dict):
        plan_dict = plan_raw
    elif hasattr(plan_raw, "model_dump"):
        plan_dict = plan_raw.model_dump()
    else:
        plan_dict = {}
    ctype = str(
        item.get("chart_type_resolved") or plan_dict.get("chart_type") or ""
    )
    if not ctype:
        return None

    if ctype == "wordcloud":
        if task.data_source == "wordcloud":
            return "wordcloud:compare:global"
        text_col = str(plan_dict.get("text_column") or "")
        csv = str(item.get("csv_path") or "")
        return f"wordcloud:single:{csv}:{text_col}"

    if task.data_source == "review_insights" and task.insight_chart_type:
        return f"{ctype}:review_insights:{task.insight_chart_type}"

    csv = str(item.get("csv_path") or "")
    parts = [
        ctype,
        str(task.data_source),
        csv,
        str(plan_dict.get("x_column") or ""),
        str(plan_dict.get("y_column") or ""),
        str(plan_dict.get("pivot_row_col") or ""),
        str(plan_dict.get("pivot_col_col") or ""),
        str(plan_dict.get("pivot_value_col") or ""),
        str(plan_dict.get("lat_column") or ""),
        str(plan_dict.get("lng_column") or ""),
        str(plan_dict.get("text_column") or ""),
    ]
    if task.data_source == "sql_run" and task.sql_run_index is not None:
        parts.append(f"idx:{task.sql_run_index}")
    if task.data_source == "supplementary_query":
        parts.append(str(task.supplementary_question or task.title or ""))
    return ":".join(parts)


def run_intelligent_visualization(
    *,
    user_query: str,
    intent: str = "descriptive",
    sql_runs: list[dict[str, Any]] | None = None,
    review_insights: dict[str, Any] | None = None,
    model=None,
    use_llm: bool = True,
    on_tool_end: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """
    智能可视化主入口：
    1. 根据用户问题 + 已有 SQL 结果规划图表套件
    2. 按需复用 sql_run / 追加查数 / 词云
    3. 返回 visualization_result 结构
    """
    runs = sql_runs or []
    suite: VizSuitePlan = plan_viz_suite(
        user_query=user_query,
        intent=intent,
        sql_runs=runs,
        review_insights=review_insights,
        model=model,
        use_llm=use_llm,
    )

    if not suite.needs_visualization or not suite.charts:
        return {
            "skipped": True,
            "summary_text": suite.reasoning or "无需生成图表。",
            "charts": [],
            "viz_plan": suite.model_dump(),
        }

    items: list[dict[str, Any]] = []
    forecast_patch: dict[str, Any] = {}
    rendered_fingerprints: set[str] = set()
    for i, task in enumerate(suite.charts):
        item = _execute_chart_task(
            task,
            sql_runs=runs,
            review_insights=review_insights,
            model=model,
            use_llm=use_llm,
            on_tool_end=on_tool_end,
        )
        if item.get("ok"):
            rfp = rendered_chart_fingerprint(item, task)
            if rfp and rfp in rendered_fingerprints:
                continue
            if rfp:
                rendered_fingerprints.add(rfp)
        items.append(item)
        if on_tool_end:
            on_tool_end(f"visualization_{i}", json.dumps(item, ensure_ascii=False))
        if item.get("forecast_summary") and not forecast_patch:
            forecast_patch["forecast_result"] = {
                "summary_text": item["forecast_summary"],
                "horizon": "6 weeks",
                "method": "linear_regression_26w",
            }

    result = merge_visualization_results(items)
    result["viz_plan"] = suite.model_dump()
    result["skipped"] = False
    if forecast_patch:
        result["forecast_result"] = forecast_patch["forecast_result"]
    return result
