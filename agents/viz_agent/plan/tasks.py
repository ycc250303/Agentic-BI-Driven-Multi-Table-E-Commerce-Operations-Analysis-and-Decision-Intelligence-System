"""套件规划 schema（与单图 VizPlan 分开，避免规划/后处理循环 import）。"""

from __future__ import annotations

from typing import Literal

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
    sql_result_index: int | None = Field(
        default=None,
        description="同一 sql_run 内 execute_sql results[] 的下标（多 SQL 子查询时区分排名/趋势等）",
    )
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
_REASON_QUESTION_HINTS = ("原因", "主题", "吐槽", "抱怨", "为什么")
_REASON_COLUMN_HINTS = ("topic", "reason", "theme", "主题", "原因", "keyword")

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
