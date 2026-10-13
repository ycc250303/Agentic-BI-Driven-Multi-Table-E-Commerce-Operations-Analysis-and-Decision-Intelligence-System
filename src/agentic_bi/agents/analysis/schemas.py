"""数据分析 Agent 私有的输入、输出与语义模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from agentic_bi.core.models import AgentResult, ArtifactRef, EvidenceEnvelope, StrictModel


class OutputMode(StrEnum):
    """期望的结果形态，不是数据库执行权限。"""

    AUTO = "auto"
    SCALAR = "scalar"
    TABLE = "table"
    RANKING = "ranking"
    TREND = "trend"
    DISTRIBUTION = "distribution"


class FilterOperator(StrEnum):
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
    """与 SQL 表达无关的业务过滤条件。"""

    field: str = Field(min_length=1, max_length=128)
    operator: FilterOperator
    value: JsonValue | list[JsonValue] | None = None

    @model_validator(mode="after")
    def validate_value(self) -> FilterSpec:
        """按运算符检查 ``value`` 的形态。

        输入：
        - ``field``：过滤字段
        - ``operator``：运算符
        - ``value``：比较值

        约束：
        - ``is_null``：不能带值
        - ``is_not_null``：不能带值
        - ``in``：值必须是列表
        - ``not_in``：值必须是列表
        - ``between``：值必须是恰好两项的列表
        - 其余运算符：必须有非空值

        输出：
        - 同一 ``FilterSpec``：形态不符时抛 ``ValueError``
        """
        no_value = {FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL}
        collection = {
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
        if self.operator in collection and not isinstance(self.value, list):
            raise ValueError(f"{self.operator.value} 的 value 必须是列表")
        if self.operator == FilterOperator.BETWEEN and (
            not isinstance(self.value, list) or len(self.value) != 2
        ):
            raise ValueError("between 的 value 必须恰好包含两个元素")
        return self


class TimeRange(StrictModel):
    """左闭右开的业务时间区间。

    结构：
    - ``start``：区间起点，可空
    - ``end``：区间终点，可空
    - ``timezone``：默认 ``UTC``

    两端都有值时 ``start`` 必须早于 ``end``。
    """

    start: datetime | None = None
    end: datetime | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_range(self) -> TimeRange:
        """拒绝空区间和反向区间。

        输入：
        - ``start``：区间起点，可空
        - ``end``：区间终点，可空

        两端都为空时视为未限定，直接通过。

        输出：
        - 同一 ``TimeRange``：``start >= end`` 时抛 ``ValueError``
        """
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("time_range.start 必须早于 time_range.end")
        return self


class AnalysisSemanticSpec(StrictModel):
    """协调器或语义解析节点产生的、与 SQL 无关的业务意图。

    结构：
    - ``metric_ids``：指标标识，至少一个
    - ``dimensions``：分组维度，可空
    - ``filters``：业务过滤，可空
    - ``time_range``：时间区间，可空
    - ``grain``：结果粒度，可空
    - ``operation``：期望结果形态
    - ``sort_by``：排序字段，与 ``sort_direction`` 成对出现
    - ``sort_direction``：排序方向
    - ``limit``：1-500，可空
    - ``ambiguities``：尚未澄清的点
    """

    metric_ids: tuple[str, ...] = Field(min_length=1)
    dimensions: tuple[str, ...] = ()
    filters: tuple[FilterSpec, ...] = ()
    time_range: TimeRange | None = None
    grain: tuple[str, ...] = ()
    operation: OutputMode = OutputMode.AUTO
    sort_by: str | None = None
    sort_direction: Literal["asc", "desc"] | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
    ambiguities: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_sort(self) -> AnalysisSemanticSpec:
        """要求排序方向必须对应一个排序字段。

        输入：
        - ``sort_by``：排序字段
        - ``sort_direction``：排序方向

        输出：
        - 同一 ``AnalysisSemanticSpec``：只有方向、没有字段时抛 ``ValueError``
        """
        if self.sort_direction is not None and self.sort_by is None:
            raise ValueError("设置 sort_direction 时必须设置 sort_by")
        return self


class AnalysisRequest(StrictModel):
    """Analysis Graph 的公开输入；一次只表示一个可验证查数任务。

    结构：
    - ``task_id``：调用方任务号
    - ``question``：已消解指代的单任务问题
    - ``semantic_spec``：协调器预填时可跳过解析，为空则由图内解析
    - ``output_mode``：期望形态
    - ``locale``：默认 ``zh-CN``，只影响解释文本

    不含模型、数据库连接和查询预算。
    """

    task_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    semantic_spec: AnalysisSemanticSpec | None = None
    output_mode: OutputMode = OutputMode.AUTO
    locale: str = Field(default="zh-CN", min_length=2, max_length=32)


class AnalysisClaim(StrictModel):
    """必须指向 Evidence 的事实陈述。

    结构：
    - ``evidence_id``：指向同一次输出里的 ``EvidenceEnvelope``
    - ``text``：该事实的一句话陈述
    """

    evidence_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=1000)


class AnalysisOutput(StrictModel):
    """Analysis Graph 的公开输出。

    结构：
    - ``task_id``：回传请求任务号
    - ``intent``：最终采用的语义规格
    - ``evidences``：可引用事实
    - ``headline``：一句话结论
    - ``claims``：每条必须引用其中一条证据
    - ``limitations``：口径或覆盖缺口
    - ``artifacts``：完整结果引用
    - ``clarification_questions``：需要用户补充的问题

    调试计数、模型名和节点耗时留在 LangSmith，不进入本结构。
    """

    task_id: str = Field(min_length=1, max_length=128)
    intent: AnalysisSemanticSpec | None = None
    evidences: tuple[EvidenceEnvelope, ...] = ()
    headline: str | None = Field(default=None, max_length=500)
    claims: tuple[AnalysisClaim, ...] = ()
    limitations: tuple[str, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    clarification_questions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_claim_references(self) -> AnalysisOutput:
        """拒绝引用了不存在证据的事实陈述。

        输入：
        - ``claims``：事实陈述，检查其中的 ``evidence_id``
        - ``evidences``：可引用事实，提供允许的 ``evidence_id``

        输出：
        - 同一 ``AnalysisOutput``：存在未知 ``evidence_id`` 时抛 ``ValueError``
        """
        evidence_ids = {evidence.evidence_id for evidence in self.evidences}
        unknown = {
            claim.evidence_id for claim in self.claims if claim.evidence_id not in evidence_ids
        }
        if unknown:
            values = ", ".join(sorted(unknown))
            raise ValueError(f"claim 引用了不存在的 evidence_id: {values}")
        return self


# 数据分析的统一返回外壳：
# - status：终态
# - value：AnalysisOutput
# - error：可展示错误
# - warnings：不改变终态的提示
AnalysisResult = AgentResult[AnalysisOutput]
