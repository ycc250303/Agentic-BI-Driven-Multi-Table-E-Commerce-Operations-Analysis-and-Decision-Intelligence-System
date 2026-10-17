"""数据分析 Agent 的输入、输出、LLM 结构化结果与内部快照。"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from agentic_bi.core.models import (
    AgentResult,
    EvidenceEnvelope,
    StrictModel,
)


class OutputMode(StrEnum):
    """用户需要的数据结果形态。"""

    SCALAR = "scalar"
    TABLE = "table"
    RANKING = "ranking"
    TREND = "trend"
    DISTRIBUTION = "distribution"


class FilterOperator(StrEnum):
    """业务过滤运算符，不直接等于任意 SQL 片段。"""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    BETWEEN = "between"
    CONTAINS = "contains"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class FilterSpec(StrictModel):
    """一个与 SQL 表达无关的业务过滤条件。"""

    field: str = Field(
        min_length=1,
        max_length=128,
        description="指标目录中的业务维度标识，例如 customer_state 或 payment_type。",
    )
    operator: FilterOperator = Field(
        description="过滤关系；between 需要两个边界值，in 和 not_in 需要值列表。",
    )
    value: JsonValue | list[JsonValue] | None = Field(
        default=None,
        description="过滤值；is_null 和 is_not_null 不允许值。",
    )

    @model_validator(mode="after")
    def validate_value(self) -> FilterSpec:
        """按运算符检查过滤值形态。"""
        no_value = {FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL}
        collections = {
            FilterOperator.IN,
            FilterOperator.NOT_IN,
            FilterOperator.BETWEEN,
        }

        if self.operator in no_value:
            if self.value is not None:
                raise ValueError(f"{self.operator.value} 不接受 value")
            return self

        if self.value is None:
            raise ValueError(f"{self.operator.value} 必须提供 value")
        if self.operator in collections and not isinstance(self.value, list):
            raise ValueError(f"{self.operator.value} 的 value 必须是列表")
        if self.operator == FilterOperator.BETWEEN and (
            not isinstance(self.value, list) or len(self.value) != 2
        ):
            raise ValueError("between 的 value 必须恰好包含两个元素")
        return self


class TimeRange(StrictModel):
    """按业务时间字段过滤的左闭右开日期区间。"""

    start: date | None = Field(
        default=None,
        description="包含该日期；例如 2017 年开始为 2017-01-01。",
    )
    end: date | None = Field(
        default=None,
        description="不包含该日期；例如完整 2017 年结束为 2018-01-01。",
    )

    @model_validator(mode="after")
    def validate_range(self) -> TimeRange:
        """拒绝空区间和反向区间。"""
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("time_range.start 必须早于 time_range.end")
        return self


class AnalysisSemanticSpec(StrictModel):
    """数据分析 Agent 对单一查数任务的业务理解。"""

    metric_ids: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "需要计算的标准业务指标标识，例如 total_gmv 或 total_orders；"
            "必须来自指标目录，可以同时包含共享同一分析粒度的多个指标。"
        ),
    )
    dimensions: tuple[str, ...] = Field(
        default=(),
        description=(
            "决定结果粒度的分组维度，例如 sales_month 或 customer_state；"
            "为空表示整段范围汇总成标量。"
        ),
    )
    filters: tuple[FilterSpec, ...] = Field(
        default=(),
        description="用户明确要求的业务过滤条件，不包括 time_range。",
    )
    time_range: TimeRange | None = Field(
        default=None,
        description="按指标默认业务时间字段应用的左闭右开日期范围。",
    )
    operation: OutputMode = Field(
        description=(
            "结果形态：scalar 是单值，table 是表格，ranking 是排序榜单，"
            "trend 是时间趋势，distribution 是分布。"
        ),
    )
    sort_by: str | None = Field(
        default=None,
        description="用于排序的当前指标或维度标识；没有排序要求时为空。",
    )
    sort_direction: Literal["asc", "desc"] | None = Field(
        default=None,
        description="升序或降序；只在 sort_by 非空时使用，省略时默认降序。",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=500,
        description="用户需要的业务结果条数，例如 TOP10 为 10。",
    )
    clarification_questions: tuple[str, ...] = Field(
        default=(),
        description=(
            "需要调用方补充、且会实质改变答案的完整问题；例如“哪个表现最好”"
            "没有说明比较对象和评价指标时，应询问具体评价指标。没有关键歧义时为空。"
        ),
    )

    @model_validator(mode="after")
    def validate_sort(self) -> AnalysisSemanticSpec:
        """排序方向必须对应一个排序字段。"""
        if self.sort_direction is not None and self.sort_by is None:
            raise ValueError("设置 sort_direction 时必须设置 sort_by")
        return self


class AnalysisRequest(StrictModel):
    """Analysis Graph 的公开输入，一次只表示一个自包含查数任务。

    - task_id：调用方生成的任务标识，用于 Trace、Artifact 和结果关联
    - question：已完成必要指代消解的自包含单任务自然语言问题；独立开发阶段可直接传自包含用户原文
    - semantic_spec：可选的已确认业务语义，仍须经过指标目录校验
    - locale：自然语言结论的语言区域，不改变指标和 SQL 口径
    """

    task_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    semantic_spec: AnalysisSemanticSpec | None = None
    locale: str = Field(default="zh-CN", min_length=2, max_length=32)


class SqlDraft(StrictModel):
    """SQL 生成模型返回的候选查询。"""

    sql: str = Field(
        min_length=1,
        max_length=30_000,
        description=(
            "一条 MySQL SELECT 或 WITH 查询；指标和维度输出列必须使用"
            " semantic_spec 中的标准标识作为别名。"
        ),
    )


class AnalysisClaim(StrictModel):
    """一条带证据引用的事实陈述。摘要模型和公开输出使用同一结构。

    - evidence_id：支持该陈述的证据标识
    - text：只陈述证据中可核对的内容
    """

    evidence_id: str = Field(
        min_length=1,
        max_length=128,
        description="支持该陈述的 Evidence 标识，必须来自输入 Evidence。",
    )
    text: str = Field(
        min_length=1,
        max_length=1000,
        description="只陈述 Evidence 可验证的数字、排名、趋势或范围。",
    )


class SummaryDraft(StrictModel):
    """摘要模型生成的证据约束结果。"""

    headline: str = Field(
        min_length=1,
        max_length=500,
        description="直接回答用户问题的一句话结论。",
    )
    claims: tuple[AnalysisClaim, ...] = Field(
        default=(),
        description="有独立证据引用的事实列表。",
    )
    limitations: tuple[str, ...] = Field(
        default=(),
        description="数据覆盖、口径、截断或无法推断因果关系等限制。",
    )


class AnalysisOutput(StrictModel):
    """Analysis Graph 的公开业务结果。

    - task_id：回传输入中的任务标识
    - intent：待澄清时已经识别出的业务语义；其他终态为空
    - evidence：成功或部分成功时可供下游引用的数据事实
    - headline：直接回答问题的一句话
    - claims：带证据标识的事实陈述
    - limitations：覆盖范围、口径、截断或不能做因果解释
    """

    task_id: str = Field(min_length=1, max_length=128)
    intent: AnalysisSemanticSpec | None = None
    evidence: EvidenceEnvelope | None = None
    headline: str | None = Field(default=None, max_length=500)
    claims: tuple[AnalysisClaim, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_claim_references(self) -> AnalysisOutput:
        """拒绝引用不存在 Evidence 的事实陈述。"""
        evidence_ids = set() if self.evidence is None else {self.evidence.evidence_id}
        unknown = {claim.evidence_id for claim in self.claims} - evidence_ids
        if unknown:
            values = ", ".join(sorted(unknown))
            raise ValueError(f"claim 引用了不存在的 evidence_id: {values}")
        return self


AnalysisResult = AgentResult[AnalysisOutput]
