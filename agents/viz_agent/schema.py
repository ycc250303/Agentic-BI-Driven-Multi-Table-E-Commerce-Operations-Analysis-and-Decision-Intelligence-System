"""可视化规划 JSON 结构（由 LLM 产出并由渲染层消费）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ChartType = Literal["line", "bar", "heatmap", "scatter", "geo_scatter", "wordcloud"]


class VizPlan(BaseModel):
    chart_type: ChartType = Field(description="图表类型枚举")
    title: str = Field(default="数据可视化", description="图表中文标题")
    x_column: str | None = None
    y_column: str | None = None
    category_column: str | None = None
    pivot_row_col: str | None = None
    pivot_col_col: str | None = None
    pivot_value_col: str | None = None
    text_column: str | None = None
    lat_column: str | None = None
    lng_column: str | None = None
    size_column: str | None = None
    hue_column: str | None = None
    reasoning: str = Field(default="", description="选型理由")


class VisualizationAgentOutput(BaseModel):
    ok: bool
    error_message: str | None = None
    user_query: str = ""
    csv_path: str = ""
    plan: VizPlan | None = None
    plan_raw_json: str = ""
    image_path: str = ""
    chart_type_resolved: str = ""
