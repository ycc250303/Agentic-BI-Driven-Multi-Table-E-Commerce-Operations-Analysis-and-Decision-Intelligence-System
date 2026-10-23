"""定义指标目录的数据结构与查询连接依赖。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field

from agentic_bi.core.models import StrictModel


class ColumnSpec(StrictModel):
    """数据库列的业务说明。

    - type：数据库类型
    - description：业务含义与空值约定
    - unit：单位，可空
    """

    type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    unit: str | None = None


class SourceSpec(StrictModel):
    """数据库中的一张表或视图。

    - kind：table 或 view
    - description：业务含义与覆盖范围
    - grain：唯一确定一行的物理列组合
    - columns：列名到业务说明
    """

    kind: Literal["table", "view"]
    description: str = Field(min_length=1)
    grain: tuple[str, ...] = Field(min_length=1)
    columns: dict[str, ColumnSpec] = Field(min_length=1)


class ScopeSpec(StrictModel):
    """固定业务总体的过滤条件。

    - description：总体的业务含义
    - predicate：基于主表别名的 MySQL 布尔表达式，始终与用户过滤取交集
    """

    description: str = Field(min_length=1)
    predicate: str = Field(min_length=1)


class JoinSpec(StrictModel):
    """从主表可达的一条连接。

    - alias：连接表在 SQL 中的固定别名
    - parent：先连接的父数据源名称
    - kind：inner 或 left
    - cardinality：父表到当前表的基数
    - on：父表与当前表之间的等值连接条件
    """

    alias: str = Field(min_length=1)
    parent: str = Field(min_length=1)
    kind: Literal["inner", "left"]
    cardinality: Literal["one_to_many", "many_to_one", "one_to_one"]
    on: str = Field(min_length=1)


class MeasurePlan(StrictModel):
    """先按原始度量粒度去重，再执行外层聚合的计算计划。

    - joins：计算度量需要的连接目标，父连接自动补全
    - grain：内层 SELECT DISTINCT 保留的物理唯一键
    - inputs：内层输出别名到原始标量表达式
    - aggregate：外层聚合表达式，仅引用 inputs 中的别名
    - sample_size：排名样本量的外层聚合表达式
    - minimum_ranking_samples：排名时每组的最低样本量
    """

    joins: tuple[str, ...] = ()
    grain: tuple[str, ...] = Field(min_length=1)
    inputs: dict[str, str] = Field(min_length=1)
    aggregate: str = Field(min_length=1)
    sample_size: str | None = None
    minimum_ranking_samples: int | None = Field(default=None, ge=1)


class ViewBinding(StrictModel):
    """在相同业务总体下可使用的视图计算方式。

    - source：视图名称
    - aggregate：视图列的外层计算表达式
    - dimensions：业务维度到视图物理列的映射，必须覆盖视图粒度
    - required_dimensions：汇总时必须保留的维度，避免重复计数或均值失真
    - time_granularity：仅完整自然月边界的时间条件可以使用视图
    """

    source: str = Field(min_length=1)
    aggregate: str = Field(min_length=1)
    dimensions: dict[str, str] = Field(min_length=1)
    required_dimensions: tuple[str, ...] = ()
    time_granularity: Literal["whole_month"] = "whole_month"

    def supports_dimensions(self, dimensions: Iterable[str], filter_fields: Iterable[str]) -> bool:
        """要求分组与过滤都有物理映射，并保留禁止汇总掉的维度。"""
        selected = set(dimensions)
        return (selected | set(filter_fields)) <= self.dimensions.keys() and set(
            self.required_dimensions
        ) <= selected


class MetricSpec(StrictModel):
    """稳定业务指标及其可执行计算定义。

    - name：指标名称
    - description：业务含义、总体与聚合规则
    - unit：单位
    - scope：固定总体标识
    - allowed_dimensions：允许分组及过滤的业务维度
    - plan：原始表查询的去重与聚合计划
    - views：与指标总体一致的视图计算绑定
    - mentions：用户可能使用的其他名称
    """

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    allowed_dimensions: tuple[str, ...] = ()
    plan: MeasurePlan
    views: tuple[ViewBinding, ...] = ()
    mentions: tuple[str, ...] = ()


class DimensionSpec(StrictModel):
    """可分组或过滤的维度及其确定性取值表达式。

    - name：维度名称
    - description：业务含义
    - expression：基于固定表别名的 MySQL 标量表达式
    - joins：表达式需要的连接目标，父连接自动补全
    - value_type：过滤值的业务类型
    - null_behavior：数据库空值及缺失业务值的处理方式
    - values：封闭枚举的数据库值到中文含义；为空表示开放取值
    - mentions：用户可能使用的其他名称
    """

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    joins: tuple[str, ...] = ()
    value_type: Literal["string", "month"]
    null_behavior: str = Field(min_length=1)
    values: dict[str, str] = Field(default_factory=dict)
    mentions: tuple[str, ...] = ()


class MetricDocument(StrictModel):
    """可执行指标目录的完整契约。

    - version：严格匹配的契约版本
    - base_source：全部原始查询的主表
    - base_alias：主表固定别名
    - time_field：左闭右开时间范围使用的物理日期字段
    - filter_only_dimensions：额外允许过滤、禁止分组的维度
    - scopes：固定业务总体
    - joins：以目标表名索引的连接依赖图
    - metrics：指标标识到定义
    - dimensions：维度标识到定义
    - sources：物理数据字典，登记本身不授予查询权限
    """

    version: Literal["2.0"]
    base_source: str
    base_alias: str
    time_field: str
    filter_only_dimensions: tuple[str, ...] = ()
    scopes: dict[str, ScopeSpec] = Field(min_length=1)
    joins: dict[str, JoinSpec] = Field(min_length=1)
    metrics: dict[str, MetricSpec] = Field(min_length=1)
    dimensions: dict[str, DimensionSpec] = Field(min_length=1)
    sources: dict[str, SourceSpec] = Field(min_length=1)

    def join_order(self, targets: Iterable[str]) -> tuple[str, ...]:
        """按父连接优先顺序展开连接依赖。"""
        ordered: dict[str, None] = {}

        def visit(target: str) -> None:
            if target == self.base_source or target in ordered:
                return
            visit(self.joins[target].parent)
            ordered[target] = None

        for target in targets:
            visit(target)
        return tuple(ordered)
