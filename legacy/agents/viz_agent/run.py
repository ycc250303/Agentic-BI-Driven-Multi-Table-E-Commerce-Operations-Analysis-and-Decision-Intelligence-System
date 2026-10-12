"""
可视化 Agent：读取数据分析 Agent（execute_sql）产出的 CSV + 列画像，
调用大模型生成 VizPlan（图表类型与字段映射），渲染并保存 PNG。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from agents.common.llm import invoke_structured
from agents.common.prompts import compose_system_prompt
from agents.viz_agent.plan.line_plan import column_is_time, normalize_line_plan
from agents.viz_agent.render.output import viz_output_dir
from agents.viz_agent.render.render import render_to_png
from agents.viz_agent.schema import VisualizationAgentOutput, VizPlan


def _parse_execute_sql(exec_json: str) -> dict[str, Any]:
    return json.loads(exec_json.strip())


def _build_human_prompt(
    user_query: str,
    df: pd.DataFrame,
    column_profiles: list[dict[str, Any]],
    data_summary_zh: str,
) -> str:
    sample = df.head(8)
    prof_lines = []
    for p in column_profiles[:20]:
        prof_lines.append(
            f"- {p.get('name')} ({p.get('inferred_type')}) 非空={p.get('non_null_count')} "
            f"示例={p.get('sample_values')}"
        )
    sample_csv = sample.to_csv(index=False)
    parts = [
        f"【用户问题】\n{user_query}",
        f"【数据摘要】\n{data_summary_zh or '（无）'}",
        f"【列画像】\n" + "\n".join(prof_lines),
        f"【行数】{len(df)}",
        f"【列名列表】{list(df.columns)}",
        "【前 8 行 CSV】",
        sample_csv,
    ]
    return "\n\n".join(parts)


def heuristic_plan(df: pd.DataFrame, user_query: str) -> VizPlan:
    cols = list(df.columns)
    ql = user_query.lower()

    lat_cols = [c for c in cols if "lat" in c.lower()]
    lng_cols = [c for c in cols if "lng" in c.lower() or "lon" in c.lower()]
    if lat_cols and lng_cols:
        return VizPlan(
            chart_type="geo_scatter",
            title="地理坐标分布",
            lat_column=lat_cols[0],
            lng_column=lng_cols[0],
            reasoning="启发式：检测到经纬度列",
        )

    text_hints = ("review", "comment", "message", "text", "评论")
    for c in cols:
        cl = c.lower()
        if any(h in cl for h in text_hints):
            if df[c].dtype == object or str(df[c].dtype).startswith("string"):
                return VizPlan(
                    chart_type="wordcloud",
                    title="文本词云",
                    text_column=c,
                    reasoning="启发式：疑似评论/文本列",
                )

    nums = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    cats = [c for c in cols if not pd.api.types.is_numeric_dtype(df[c])]
    time_cols = [c for c in cols if column_is_time(c)]

    if "热力" in user_query or "heatmap" in ql or "矩阵" in user_query:
        if len(cols) >= 3:
            cat_like = [
                c for c in cols if (c not in nums) or len(df[c].dropna().unique()) <= 30
            ]
            if len(cat_like) >= 2 and nums:
                return VizPlan(
                    chart_type="heatmap",
                    title="交叉热力图",
                    pivot_row_col=cat_like[0],
                    pivot_col_col=cat_like[1],
                    pivot_value_col=nums[0],
                    reasoning="启发式：用户语义偏热力矩阵且存在可用列",
                )

    if time_cols and nums:
        series_cols = [c for c in cats if c not in time_cols]
        if len(time_cols) >= 1 and len(nums) >= 1 and len(series_cols) == 1:
            return VizPlan(
                chart_type="line",
                title="趋势折线",
                x_column=time_cols[0],
                y_column=nums[0],
                category_column=series_cols[0],
                reasoning="启发式：时间 + 分系列 + 数值，多系列折线",
            )
        return VizPlan(
            chart_type="line",
            title="趋势折线",
            x_column=time_cols[0],
            y_column=nums[0],
            reasoning="启发式：时间/年月字段 + 数值列",
        )

    if cats and nums:
        cat0 = cats[0]
        return VizPlan(
            chart_type="bar",
            title="类别对比",
            x_column=cat0,
            y_column=nums[0],
            reasoning="启发式：类别列 + 数值列",
        )

    if len(nums) >= 2:
        return VizPlan(
            chart_type="scatter",
            title="数值关系散点",
            x_column=nums[0],
            y_column=nums[1],
            reasoning="启发式：双数值列",
        )

    if cats:
        return VizPlan(
            chart_type="bar",
            title=f"{cats[0]} 频次分布",
            category_column=cats[0],
            reasoning="启发式：单列类别",
        )

    return VizPlan(
        chart_type="bar",
        title="数据概览",
        x_column=cols[0],
        reasoning="启发式：兜底条形图",
    )


def _plan_to_raw_json(plan: VizPlan) -> str:
    return json.dumps(plan.model_dump(), ensure_ascii=False)


def plan_with_llm(
    user_query: str,
    df: pd.DataFrame,
    column_profiles: list[dict[str, Any]],
    data_summary_zh: str,
    *,
    model=None,
) -> tuple[VizPlan, str]:
    """单图选型：CSV 样本 + 列画像 → VizPlan（chart_type 与列映射）。

    Prompt: config/visualization_agent/plan_chart.md。默认 ``get_structured_llm()``；
    ``model`` 仅测试注入。模型不写 matplotlib 代码。
    """
    system = compose_system_prompt("visualization_agent", "plan_chart.md")
    human = _build_human_prompt(user_query, df, column_profiles, data_summary_zh)
    response = invoke_structured(
        VizPlan,
        [SystemMessage(content=system), HumanMessage(content=human)],
        model=model,
    )
    plan = response if isinstance(response, VizPlan) else VizPlan.model_validate(response)
    return plan, plan.model_dump_json(ensure_ascii=False)


def run_visualization_agent(
    *,
    user_query: str,
    execute_sql_json: str | None = None,
    csv_path: str | Path | None = None,
    model=None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """单图渲染（内部）。套件入口见 ``run_intelligent_visualization``。

    提供 ``execute_sql_json``（须 ``ok=true``）或 ``csv_path`` 之一。
    选型默认 DeepSeek；失败回退启发式。
    """
    csv_p: Path | None = None
    profiles: list[dict[str, Any]] = []
    summary_zh = ""

    if execute_sql_json:
        payload = _parse_execute_sql(execute_sql_json)
        if not payload.get("ok"):
            return VisualizationAgentOutput(
                ok=False,
                error_message=payload.get("error_message") or "execute_sql 未成功，缺少可视化输入",
                user_query=user_query,
            ).model_dump()
        csv_p = Path(str(payload.get("result_csv_path") or ""))
        profiles = list(payload.get("column_profiles") or [])
        summary_zh = str(payload.get("data_summary_zh") or "")
    elif csv_path:
        csv_p = Path(csv_path)
    else:
        return VisualizationAgentOutput(
            ok=False,
            error_message="必须提供 execute_sql_json 或 csv_path",
            user_query=user_query,
        ).model_dump()

    if not csv_p.is_file():
        return VisualizationAgentOutput(
            ok=False,
            error_message=f"CSV 不存在：{csv_p}",
            user_query=user_query,
        ).model_dump()

    df = pd.read_csv(csv_p)
    if df.empty:
        return VisualizationAgentOutput(
            ok=False,
            error_message="CSV 无数据行",
            user_query=user_query,
            csv_path=str(csv_p.resolve()),
        ).model_dump()

    plan_raw = ""
    plan: VizPlan
    try:
        plan, plan_raw = plan_with_llm(
            user_query, df, profiles, summary_zh, model=model
        )
    except Exception as e:
        plan = heuristic_plan(df, user_query)
        plan_raw = _plan_to_raw_json(plan) + f"\n<!-- llm_fallback: {e} -->"

    plan = normalize_line_plan(df, plan)

    out_dir = output_dir or viz_output_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_type = plan.chart_type.replace("/", "-")
    png_path = out_dir / f"viz_{safe_type}_{ts}.png"

    try:
        img = render_to_png(df, plan, png_path)
    except Exception as e:
        return VisualizationAgentOutput(
            ok=False,
            error_message=f"渲染失败：{e}",
            user_query=user_query,
            csv_path=str(csv_p.resolve()),
            plan=plan,
            plan_raw_json=plan_raw,
            chart_type_resolved=plan.chart_type,
        ).model_dump()

    return VisualizationAgentOutput(
        ok=True,
        user_query=user_query,
        csv_path=str(csv_p.resolve()),
        plan=plan,
        plan_raw_json=plan_raw,
        image_path=img,
        chart_type_resolved=plan.chart_type,
    ).model_dump()


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="单图渲染调试：给定 CSV 出一张 PNG。产品路径请走协调器。"
    )
    parser.add_argument("--csv", type=str, required=True, help="查询结果 CSV 路径")
    parser.add_argument(
        "--query",
        type=str,
        default="可视化这张结果表",
        help="用户业务问题（用于图表选型）",
    )
    args = parser.parse_args()

    out = run_visualization_agent(
        user_query=args.query,
        csv_path=args.csv,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out.get("ok") else 1)
