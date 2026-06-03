"""
可选的数据模板库（仅 CLI `--dashboard` 调试用）。

正常协调器流程**不会**自动跑全套图；请使用 `intelligent_viz.run_intelligent_visualization`，
由 LLM 根据用户问题与 SQL 结果按需规划图表。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from agents.nlp_agent.db import query
from agents.nlp_agent.tools.wordcloud_data import run_wordcloud_data

from agents.viz_agent.forecast import forecast_weekly_gmv
from agents.viz_agent.render import render_to_png
from agents.viz_agent.render_context import RenderExtras
from agents.viz_agent.schema import VizPlan, VisualizationAgentOutput


@dataclass(frozen=True)
class PresetChartSpec:
    chart_id: str
    title: str
    sql: str
    plan: VizPlan
    extras_fn: Callable[[], RenderExtras | None] | None = None


def _monthly_sales_spec() -> PresetChartSpec:
    return PresetChartSpec(
        chart_id="monthly_gmv_forecast",
        title="月度 GMV 趋势与未来 6 周预测",
        sql="""
            SELECT `year_month`, `total_gmv`, `total_orders`
            FROM `mv_monthly_sales`
            ORDER BY `year_month`
        """,
        plan=VizPlan(
            chart_type="line",
            title="月度 GMV 趋势与未来 6 周预测",
            x_column="year_month",
            y_column="total_gmv",
            reasoning="预聚合视图 mv_monthly_sales + 周度线性外推预测",
        ),
        extras_fn=lambda: RenderExtras(forecast=forecast_weekly_gmv(horizon_weeks=6)),
    )


def _geo_state_spec() -> PresetChartSpec:
    return PresetChartSpec(
        chart_id="state_geo_bubble",
        title="巴西各州销售额与订单量地理分布",
        sql="""
            SELECT
                s.`customer_state`,
                g.`lat`,
                g.`lng`,
                SUM(s.`total_gmv`) AS `total_gmv`,
                SUM(s.`total_orders`) AS `total_orders`
            FROM `mv_state_sales` s
            INNER JOIN (
                SELECT
                    `geolocation_state` AS `customer_state`,
                    AVG(`geolocation_lat`) AS `lat`,
                    AVG(`geolocation_lng`) AS `lng`
                FROM `geolocation`
                GROUP BY `geolocation_state`
            ) g ON s.`customer_state` = g.`customer_state`
            GROUP BY s.`customer_state`, g.`lat`, g.`lng`
            ORDER BY `total_gmv` DESC
        """,
        plan=VizPlan(
            chart_type="geo_scatter",
            title="巴西各州销售额与订单量地理分布",
            lat_column="lat",
            lng_column="lng",
            size_column="total_orders",
            hue_column="total_gmv",
            x_column="customer_state",
            reasoning="mv_state_sales × geolocation 州中心点气泡",
        ),
        extras_fn=lambda: RenderExtras(color_column="total_gmv"),
    )


def _state_aov_bar_spec() -> PresetChartSpec:
    return PresetChartSpec(
        chart_id="state_avg_basket",
        title="各州客单价（GMV / 订单）对比 Top15",
        sql="""
            SELECT
                `customer_state`,
                SUM(`total_gmv`) / NULLIF(SUM(`total_orders`), 0) AS `avg_basket`
            FROM `mv_state_sales`
            GROUP BY `customer_state`
            HAVING SUM(`total_orders`) > 0
            ORDER BY `avg_basket` DESC
            LIMIT 15
        """,
        plan=VizPlan(
            chart_type="bar",
            title="各州客单价（GMV / 订单）对比 Top15",
            x_column="customer_state",
            y_column="avg_basket",
            reasoning="mv_state_sales 客单价排名",
        ),
        extras_fn=lambda: RenderExtras(value_format="currency"),
    )


def _top_category_bar_spec() -> PresetChartSpec:
    return PresetChartSpec(
        chart_id="top_category_gmv",
        title="Top15 品类销售额（GMV）",
        sql="""
            SELECT
                `product_category_english`,
                SUM(`total_gmv`) AS `total_gmv`
            FROM `mv_category_sales`
            GROUP BY `product_category_english`
            ORDER BY `total_gmv` DESC
            LIMIT 15
        """,
        plan=VizPlan(
            chart_type="bar",
            title="Top15 品类销售额（GMV）",
            x_column="product_category_english",
            y_column="total_gmv",
            reasoning="mv_category_sales 品类排名",
        ),
        extras_fn=lambda: RenderExtras(value_format="currency"),
    )


def _payment_bar_spec() -> PresetChartSpec:
    return PresetChartSpec(
        chart_id="payment_frequency",
        title="支付方式交易笔数分布",
        sql="""
            SELECT
                `payment_type`,
                SUM(`total_transactions`) AS `transaction_count`
            FROM `mv_payment_dist`
            GROUP BY `payment_type`
            ORDER BY `transaction_count` DESC
        """,
        plan=VizPlan(
            chart_type="bar",
            title="支付方式交易笔数分布",
            x_column="payment_type",
            y_column="transaction_count",
            reasoning="mv_payment_dist 支付偏好",
        ),
    )


def _payment_installment_heatmap_spec() -> PresetChartSpec:
    return PresetChartSpec(
        chart_id="payment_installment_matrix",
        title="支付方式 × 分期数 交易矩阵",
        sql="""
            SELECT
                p.`payment_type`,
                p.`payment_installments`,
                COUNT(*) AS `transaction_count`
            FROM `payments` p
            INNER JOIN `orders` o ON p.`order_id` = o.`order_id`
            WHERE o.`order_status` IN (
                'delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced'
            )
              AND p.`payment_installments` BETWEEN 1 AND 12
            GROUP BY p.`payment_type`, p.`payment_installments`
        """,
        plan=VizPlan(
            chart_type="heatmap",
            title="支付方式 × 分期数 交易矩阵",
            pivot_row_col="payment_type",
            pivot_col_col="payment_installments",
            pivot_value_col="transaction_count",
            reasoning="payments 交叉矩阵热力图",
        ),
    )


def _weight_freight_scatter_spec() -> PresetChartSpec:
    return PresetChartSpec(
        chart_id="weight_freight_scatter",
        title="商品重量 vs 运费（气泡=订单量，颜色=配送状态）",
        sql="""
            SELECT
                ROUND(p.`product_weight_g` / 500) * 500 AS `weight_bucket_g`,
                ROUND(oi.`freight_value`, 1) AS `freight_value`,
                COUNT(DISTINCT oi.`order_id`) AS `order_count`,
                CASE
                    WHEN o.`order_status` = 'delivered'
                         AND o.`order_delivered_customer_date` <= o.`order_estimated_delivery_date`
                        THEN '准时'
                    WHEN o.`order_status` = 'delivered' THEN '延迟'
                    ELSE '其他'
                END AS `delivery_status`
            FROM `order_items` oi
            INNER JOIN `products` p ON oi.`product_id` = p.`product_id`
            INNER JOIN `orders` o ON oi.`order_id` = o.`order_id`
            WHERE p.`product_weight_g` > 0
              AND oi.`freight_value` >= 0
            GROUP BY `weight_bucket_g`, `freight_value`, `delivery_status`
            HAVING `order_count` >= 2
            ORDER BY `order_count` DESC
            LIMIT 800
        """,
        plan=VizPlan(
            chart_type="scatter",
            title="商品重量 vs 运费（气泡=订单量，颜色=配送状态）",
            x_column="weight_bucket_g",
            y_column="freight_value",
            size_column="order_count",
            hue_column="delivery_status",
            reasoning="order_items × products 重量运费关系",
        ),
    )


def _wordcloud_compare_spec() -> PresetChartSpec:
    return PresetChartSpec(
        chart_id="review_wordcloud_compare",
        title="好评 vs 差评 评论词云对比",
        sql="SELECT 1 AS `_placeholder` LIMIT 0",
        plan=VizPlan(
            chart_type="wordcloud",
            title="好评 vs 差评 评论词云对比",
            reasoning="NLP wordcloud_data 好评/差评对比",
        ),
        extras_fn=lambda: RenderExtras(
            wordcloud_compare=_load_wordcloud_compare(),
            subtitle="左：好评(≥4分)  右：差评(≤2分)",
        ),
    )


def _load_wordcloud_compare() -> dict[str, dict[str, int]]:
    wc = run_wordcloud_data(top_n=80, pos_sample=4000, neg_sample=4000)
    pos = wc.get("positive") or {}
    neg = wc.get("negative") or {}
    if not pos and not neg:
        raise ValueError("词云数据为空")
    return {"positive": pos, "negative": neg}


def get_preset_chart_specs() -> list[PresetChartSpec]:
    return [
        _monthly_sales_spec(),
        _geo_state_spec(),
        _state_aov_bar_spec(),
        _top_category_bar_spec(),
        _payment_bar_spec(),
        _payment_installment_heatmap_spec(),
        _weight_freight_scatter_spec(),
        _wordcloud_compare_spec(),
    ]


def _fetch_dataframe(spec: PresetChartSpec) -> pd.DataFrame:
    if spec.chart_id == "review_wordcloud_compare":
        return pd.DataFrame()
    rows = query(spec.sql.strip())
    return pd.DataFrame(rows)


def _viz_output_dir(base: Path | None = None) -> Path:
    if base is not None:
        return base.resolve()
    import os

    raw = os.environ.get("AGENTIC_BI_VIZ_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parent / "chart_output").resolve()


def run_preset_chart(
    spec: PresetChartSpec,
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    out_dir = _viz_output_dir(output_dir)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    png_path = out_dir / f"preset_{spec.chart_id}_{ts}.png"

    extras: RenderExtras | None = None
    try:
        if spec.extras_fn is not None:
            extras = spec.extras_fn()
    except Exception as e:
        return VisualizationAgentOutput(
            ok=False,
            error_message=f"扩展数据准备失败（{spec.chart_id}）：{e}",
            user_query=spec.title,
            chart_type_resolved=spec.plan.chart_type,
        ).model_dump() | {"chart_id": spec.chart_id, "preset": True}

    try:
        df = _fetch_dataframe(spec)
        if spec.chart_id != "review_wordcloud_compare" and df.empty:
            raise ValueError("查询结果为空")
        img = render_to_png(df, spec.plan, png_path, extras=extras)
    except Exception as e:
        return VisualizationAgentOutput(
            ok=False,
            error_message=f"预设图渲染失败（{spec.chart_id}）：{e}",
            user_query=spec.title,
            plan=spec.plan,
            chart_type_resolved=spec.plan.chart_type,
        ).model_dump() | {"chart_id": spec.chart_id, "preset": True}

    result = VisualizationAgentOutput(
        ok=True,
        user_query=spec.title,
        plan=spec.plan,
        plan_raw_json=spec.plan.model_dump_json(),
        image_path=img,
        chart_type_resolved=spec.plan.chart_type,
    ).model_dump()
    result["chart_id"] = spec.chart_id
    result["preset"] = True
    if extras and extras.forecast and extras.forecast.get("ok"):
        result["forecast_summary"] = extras.forecast.get("summary_text")
    return result


def run_dashboard_charts(*, output_dir: Path | None = None) -> list[dict[str, Any]]:
    """生成全套高价值预设图表，返回 VisualizationAgentOutput 风格 dict 列表。"""
    items: list[dict[str, Any]] = []
    for spec in get_preset_chart_specs():
        items.append(run_preset_chart(spec, output_dir=output_dir))
    return items


def merge_dashboard_with_query_charts(
    preset_items: list[dict[str, Any]],
    query_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """预设图优先；查询触发的图仅补充尚未覆盖的 chart_type。"""
    merged = list(preset_items)
    covered = {
        str(i.get("chart_type_resolved") or "")
        for i in preset_items
        if i.get("ok")
    }
    for item in query_items:
        ctype = str(item.get("chart_type_resolved") or "")
        if item.get("ok") and ctype and ctype in covered:
            continue
        merged.append(item)
        if item.get("ok") and ctype:
            covered.add(ctype)
    return merged
