"""读取指标语义并为当前任务生成最小业务上下文。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from agentic_bi.core.models import StrictModel


class MetricSpec(StrictModel):
    """稳定业务指标的定义。

    - name：指标名称
    - description：指标含义
    - unit：单位
    - formula：计算公式
    - time_field：默认时间字段
    - allowed_dimensions：允许的分组维度
    - candidate_sources：候选数据源，至少一个
    """

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    time_field: str = Field(min_length=1)
    allowed_dimensions: tuple[str, ...] = ()
    candidate_sources: tuple[str, ...] = Field(min_length=1)


class DimensionSpec(StrictModel):
    """一个可分组或过滤的业务维度。

    - name：维度名称
    - description：业务含义
    - sources：该维度出现在哪些数据源
    """

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    sources: tuple[str, ...] = Field(min_length=1)


class ColumnSpec(StrictModel):
    """数据库列的业务说明。

    - type：数据库类型
    - description：业务含义
    - unit：单位，可空
    """

    type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    unit: str | None = None


class SourceSpec(StrictModel):
    """允许查询的一张表或视图。

    - kind：table 或 view
    - description：业务含义
    - grain：一行代表的粒度
    - columns：列名到业务说明
    - joins：允许的 JOIN 说明，可空
    """

    kind: Literal["table", "view"]
    description: str = Field(min_length=1)
    grain: tuple[str, ...] = Field(min_length=1)
    columns: dict[str, ColumnSpec] = Field(min_length=1)
    joins: tuple[str, ...] = ()


class MetricDocument(StrictModel):
    """metrics.yaml 的完整结构。

    - version：目录版本
    - metrics：指标标识到定义
    - dimensions：维度标识到定义
    - sources：数据源名称到定义
    """

    version: str = Field(min_length=1)
    metrics: dict[str, MetricSpec] = Field(min_length=1)
    dimensions: dict[str, DimensionSpec] = Field(min_length=1)
    sources: dict[str, SourceSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> MetricDocument:
        """拒绝指标或维度引用不存在的数据源。

        输入：
        - metrics：指标定义，检查允许维度和候选数据源
        - dimensions：维度定义，检查其数据源
        - sources：已登记的数据源

        输出：
        - 同一实例：引用未知维度或数据源时抛 ``ValueError``
        """
        source_names = set(self.sources)

        for metric_id, metric in self.metrics.items():
            unknown_dimensions = set(metric.allowed_dimensions) - set(self.dimensions)
            if unknown_dimensions:
                values = ", ".join(sorted(unknown_dimensions))
                raise ValueError(f"指标 {metric_id} 引用了未知维度: {values}")

            unknown_sources = set(metric.candidate_sources) - source_names
            if unknown_sources:
                values = ", ".join(sorted(unknown_sources))
                raise ValueError(f"指标 {metric_id} 引用了未知数据源: {values}")

        for dimension_id, dimension in self.dimensions.items():
            unknown_sources = set(dimension.sources) - source_names
            if unknown_sources:
                values = ", ".join(sorted(unknown_sources))
                raise ValueError(f"维度 {dimension_id} 引用了未知数据源: {values}")

        return self


class MetricCatalog:
    """指标、维度和允许数据源的只读目录。"""

    def __init__(self, document: MetricDocument) -> None:
        self._document = document

    @classmethod
    def load(cls, path: Path) -> MetricCatalog:
        """从 YAML 加载并校验指标目录。

        输入：
        - path：metrics.yaml 路径

        输出：
        - 指标目录：文件不存在时抛 ``FileNotFoundError``；根节点不是对象时抛 ``ValueError``
        """
        if not path.is_file():
            raise FileNotFoundError(f"指标配置不存在: {path}")

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("指标配置根节点必须是对象")

        return cls(MetricDocument.model_validate(raw))

    @property
    def version(self) -> str:
        return self._document.version

    def validate_intent(
        self,
        *,
        metric_ids: Iterable[str],
        dimensions: Iterable[str],
        filter_fields: Iterable[str],
        sort_by: str | None,
    ) -> None:
        """确定性校验指标、维度、过滤字段和排序字段。

        输入：
        - metric_ids：请求的指标
        - dimensions：分组维度
        - filter_fields：过滤字段，必须是已登记维度
        - sort_by：排序字段，为空则不检查

        约束：
        - 维度必须落在每个指标的允许维度内
        - sort_by 必须是当前请求中的指标或维度

        输出：
        - 无：不满足时抛 ``ValueError``
        """
        selected_metrics = tuple(metric_ids)
        selected_dimensions = tuple(dimensions)
        selected_filters = tuple(filter_fields)

        unknown_metrics = set(selected_metrics) - set(self._document.metrics)
        if unknown_metrics:
            values = ", ".join(sorted(unknown_metrics))
            raise ValueError(f"未知指标: {values}")

        unknown_dimensions = set(selected_dimensions) - set(self._document.dimensions)
        if unknown_dimensions:
            values = ", ".join(sorted(unknown_dimensions))
            raise ValueError(f"未知维度: {values}")

        unknown_filters = set(selected_filters) - set(self._document.dimensions)
        if unknown_filters:
            values = ", ".join(sorted(unknown_filters))
            raise ValueError(f"未知过滤字段: {values}")

        for metric_id in selected_metrics:
            allowed = set(self._document.metrics[metric_id].allowed_dimensions)
            unsupported = set(selected_dimensions) - allowed
            if unsupported:
                values = ", ".join(sorted(unsupported))
                raise ValueError(f"指标 {metric_id} 不支持以下维度: {values}")

        if sort_by is not None:
            allowed_sort_fields = set(selected_metrics) | set(selected_dimensions)
            if sort_by not in allowed_sort_fields:
                raise ValueError("sort_by 必须是当前请求中的指标或维度")

    def validate_result_columns(
        self,
        *,
        columns: Iterable[str],
        metric_ids: Iterable[str],
        dimensions: Iterable[str],
    ) -> None:
        """要求 SQL 输出列包含请求指标和分组维度的标准名称。

        输入：
        - columns：实际结果列
        - metric_ids：请求的指标
        - dimensions：分组维度

        输出：
        - 无：缺少标准列时抛 ``ValueError``
        """
        actual = set(columns)
        expected = set(metric_ids) | set(dimensions)
        missing = expected - actual
        if missing:
            values = ", ".join(sorted(missing))
            raise ValueError(f"SQL 结果缺少标准输出列: {values}")

    def render_metric_context(self) -> str:
        """为语义解析节点渲染指标与维度的业务说明。

        输入：
        - 无：使用目录中的全部指标和维度

        输出：
        - 文本：含版本、指标口径和维度含义
        """
        lines = [f"指标目录版本：{self.version}", "", "可用指标："]

        for metric_id, metric in self._document.metrics.items():
            dimensions = "、".join(metric.allowed_dimensions) or "不允许分组"
            lines.extend(
                [
                    f"- {metric_id}（{metric.name}）",
                    f"  含义：{metric.description}",
                    f"  单位：{metric.unit}",
                    f"  口径：{metric.formula}",
                    f"  默认时间字段：{metric.time_field}",
                    f"  允许维度：{dimensions}",
                ]
            )

        lines.extend(["", "可用维度："])
        for dimension_id, dimension in self._document.dimensions.items():
            lines.append(f"- {dimension_id}（{dimension.name}）：{dimension.description}")

        return "\n".join(lines)

    def render_schema_context(
        self,
        *,
        metric_ids: Iterable[str],
        dimensions: Iterable[str],
    ) -> str:
        """只渲染当前任务可能使用的数据源、字段含义、粒度和 JOIN。

        输入：
        - metric_ids：请求的指标，用来选择候选数据源
        - dimensions：分组维度，用来补上维度所在数据源

        输出：
        - 文本：不含未用到的数据源
        """
        source_names = self._relevant_sources(
            metric_ids=metric_ids,
            dimensions=dimensions,
        )
        lines: list[str] = []

        for source_name in source_names:
            source = self._document.sources[source_name]
            grain = " + ".join(source.grain)
            lines.extend(
                [
                    f"数据源 {source_name}",
                    f"- 类型：{source.kind}",
                    f"- 业务含义：{source.description}",
                    f"- 数据粒度：{grain}",
                    "- 字段：",
                ]
            )

            for column_name, column in source.columns.items():
                unit = f"，单位：{column.unit}" if column.unit else ""
                lines.append(
                    f"  - {column_name}：{column.description}；数据库类型：{column.type}{unit}"
                )

            if source.joins:
                lines.append("- 允许 JOIN：")
                lines.extend(f"  - {join}" for join in source.joins)

            lines.append("")

        return "\n".join(lines).strip()

    def allowed_sources(
        self,
        *,
        metric_ids: Iterable[str],
        dimensions: Iterable[str],
    ) -> dict[str, frozenset[str]]:
        """返回当前任务允许访问的数据源及列白名单。

        输入：
        - metric_ids：请求的指标
        - dimensions：分组维度

        输出：
        - 数据源到列名：只包含当前任务相关的来源
        """
        names = self._relevant_sources(
            metric_ids=metric_ids,
            dimensions=dimensions,
        )
        return {name: frozenset(self._document.sources[name].columns) for name in names}

    def source_kinds(
        self,
        source_names: Iterable[str],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """把数据源拆成原始表和视图。

        输入：
        - source_names：数据源名称

        输出：
        - 原始表和视图：按 kind 分成两组，保持传入顺序
        """
        tables: list[str] = []
        views: list[str] = []

        for source_name in source_names:
            source = self._document.sources[source_name]
            if source.kind == "view":
                views.append(source_name)
            else:
                tables.append(source_name)

        return tuple(tables), tuple(views)

    def units_for(self, metric_ids: Iterable[str]) -> dict[str, str]:
        """返回指标与单位映射。

        输入：
        - metric_ids：指标标识

        输出：
        - 指标到单位
        """
        return {metric_id: self._document.metrics[metric_id].unit for metric_id in metric_ids}

    def _relevant_sources(
        self,
        *,
        metric_ids: Iterable[str],
        dimensions: Iterable[str],
    ) -> tuple[str, ...]:
        ordered: dict[str, None] = {}

        for metric_id in metric_ids:
            metric = self._document.metrics.get(metric_id)
            if metric is None:
                raise ValueError(f"未知指标: {metric_id}")
            for source_name in metric.candidate_sources:
                ordered.setdefault(source_name, None)

        for dimension_id in dimensions:
            dimension = self._document.dimensions.get(dimension_id)
            if dimension is None:
                raise ValueError(f"未知维度: {dimension_id}")
            for source_name in dimension.sources:
                ordered.setdefault(source_name, None)

        return tuple(ordered)

    def all_sources(self) -> Mapping[str, SourceSpec]:
        """返回只读数据源映射。

        输入：
        - 无

        输出：
        - 数据源名称到定义
        """
        return self._document.sources
