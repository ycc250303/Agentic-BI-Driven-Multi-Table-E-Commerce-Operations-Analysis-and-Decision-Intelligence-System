"""读取指标语义并为当前任务生成最小业务上下文。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

import yaml

from agentic_bi.core.models import EvidenceSource
from agentic_bi.data.metric_schema import MetricDocument, SourceSpec


class MetricCatalog:
    """指标、维度和允许数据源的只读目录；下游查询方法接收已校验的业务语义。"""

    def __init__(self, document: MetricDocument) -> None:
        self._document = document

    @classmethod
    def load(cls, path: Path) -> MetricCatalog:
        """从 YAML 加载指标目录并校验数据结构。

        输入：
        - path：metrics.yaml 路径

        输出：
        - 指标目录：文件不存在时抛 ``FileNotFoundError``；结构错误时抛 ``ValueError``
        """
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))

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
            unsupported_filters = set(selected_filters) - (
                allowed | set(self._document.filter_only_dimensions)
            )
            if unsupported_filters:
                values = ", ".join(sorted(unsupported_filters))
                raise ValueError(f"指标 {metric_id} 不支持以下过滤维度: {values}")

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
                    f"  默认范围：{self._document.scopes[metric.scope].description}",
                    f"  默认时间字段：{self._document.time_field}，左闭右开日期区间",
                    f"  允许维度：{dimensions}",
                    "  允许过滤："
                    + "、".join(
                        (*metric.allowed_dimensions, *self._document.filter_only_dimensions)
                    ),
                ]
            )

        lines.extend(["", "可用维度："])
        for dimension_id, dimension in self._document.dimensions.items():
            lines.append(f"- {dimension_id}（{dimension.name}）：{dimension.description}")
            lines.append(f"  取值类型：{dimension.value_type}；缺失处理：{dimension.null_behavior}")
            if dimension.values:
                lines.append("  合法取值：" + json.dumps(dimension.values, ensure_ascii=False))

        return "\n".join(lines)

    def render_schema_context(
        self,
        *,
        metric_ids: Iterable[str],
        dimensions: Iterable[str],
        filter_fields: Iterable[str] = (),
    ) -> str:
        """只渲染当前任务可能使用的数据源、字段含义、粒度和 JOIN。

        输入：
        - metric_ids：请求的指标，用来选择候选数据源
        - dimensions：分组维度，用来补上维度所在数据源
        - filter_fields：仅用于过滤的维度，补全其连接依赖

        输出：
        - 文本：不含未用到的数据源
        """
        selected_metrics = tuple(metric_ids)
        selected_dimensions = tuple(dimensions)
        selected_filters = tuple(filter_fields)
        source_names = self._relevant_sources(
            metric_ids=selected_metrics,
            dimensions=selected_dimensions,
            filter_fields=selected_filters,
        )
        lines = [
            "计算计划：内层 SELECT DISTINCT 保留物理粒度键、输入表达式及请求维度，外层聚合。",
            "每个指标单独聚合后按维度合并，维度 NULL 使用空值安全等值连接；无维度时合并单行结果。",
            "固定总体、用户过滤、左闭右开时间条件取交集；仅排名应用最低样本数。",
            "度量计划字段：joins=连接目标；grain=内层物理去重键；inputs=内层别名到行级表达式；",
            "aggregate=外层聚合；sample_size=外层样本量；minimum_ranking_samples=排名最低样本数。",
            "视图绑定字段：source=视图；aggregate=视图列计算；dimensions=维度到物理列映射；",
            "required_dimensions=必须保留的分组维度；time_granularity=whole_month 表示完整自然月。",
            "需要样本门槛的排名使用原始表计划。",
            f"主表：{self._document.base_source} AS {self._document.base_alias}",
            f"时间字段：{self._document.time_field}",
        ]
        for metric_id in selected_metrics:
            metric = self._document.metrics[metric_id]
            scope = self._document.scopes[metric.scope]
            lines.append(f"指标 {metric_id}：{metric.description}；单位：{metric.unit}")
            lines.append(f"固定总体：{scope.description}；WHERE ({scope.predicate})")
            lines.append("度量计划：" + metric.plan.model_dump_json())
            for binding in metric.views:
                if binding.supports_dimensions(selected_dimensions, selected_filters):
                    lines.append("视图绑定（仅完整自然月范围）：" + binding.model_dump_json())
        for name in dict.fromkeys((*selected_dimensions, *selected_filters)):
            dimension = self._document.dimensions[name]
            lines.append(
                f"维度 {name}：{dimension.description}；表达式：{dimension.expression}；"
                f"缺失处理：{dimension.null_behavior}"
            )

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

            if source_name in self._document.joins:
                join = self._document.joins[source_name]
                lines.append(
                    f"- 连接：{join.kind.upper()} JOIN {source_name} AS {join.alias} "
                    f"ON {join.on}；父表到当前表的基数：{join.cardinality}"
                )

            lines.append("")

        return "\n".join(lines).strip()

    def allowed_sources(
        self,
        *,
        metric_ids: Iterable[str],
        dimensions: Iterable[str],
        filter_fields: Iterable[str] = (),
    ) -> dict[str, frozenset[str]]:
        """返回当前任务允许访问的数据源及列白名单。

        输入：
        - metric_ids：请求的指标
        - dimensions：分组维度
        - filter_fields：仅用于过滤的维度

        输出：
        - 数据源到列名：只包含当前任务相关的来源
        """
        names = self._relevant_sources(
            metric_ids=metric_ids,
            dimensions=dimensions,
            filter_fields=filter_fields,
        )
        return {name: frozenset(self._document.sources[name].columns) for name in names}

    def evidence_sources(
        self,
        source_names: Iterable[str],
    ) -> tuple[EvidenceSource, ...]:
        """把实际访问的数据源转换为证据来源。

        输入：
        - source_names：数据源名称

        输出：
        - 证据来源：每项包含数据源名称与类型，保持传入顺序
        """
        return tuple(
            EvidenceSource(
                name=source_name,
                kind=self._document.sources[source_name].kind,
            )
            for source_name in source_names
        )

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
        filter_fields: Iterable[str] = (),
    ) -> tuple[str, ...]:
        selected_metrics = tuple(metric_ids)
        selected_dimensions = tuple(dimensions)
        selected_filters = tuple(filter_fields)
        ordered = {self._document.base_source: None}
        for metric_id in selected_metrics:
            metric = self._document.metrics[metric_id]
            targets = list(metric.plan.joins)
            for name in dict.fromkeys((*selected_dimensions, *selected_filters)):
                targets.extend(self._document.dimensions[name].joins)
            ordered.update(dict.fromkeys(self._document.join_order(targets)))
            for binding in metric.views:
                if binding.supports_dimensions(selected_dimensions, selected_filters):
                    ordered[binding.source] = None
        return tuple(ordered)

    def all_sources(self) -> Mapping[str, SourceSpec]:
        """返回只读数据源映射。

        输入：
        - 无

        输出：
        - 数据源名称到定义
        """
        return self._document.sources
