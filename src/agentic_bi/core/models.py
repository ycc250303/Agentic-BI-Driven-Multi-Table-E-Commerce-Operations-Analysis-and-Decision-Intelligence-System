"""真正跨 Agent 使用的稳定契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class StrictModel(BaseModel):
    """跨边界契约的共同校验规则：拒绝多余字段，实例冻结，字符串去首尾空白，允许字段名或别名填充。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class AgentStatus(StrEnum):
    """所有 Agent 共用的终态。

    - success：证据完整
    - partial：证据可用，但解释或非关键步骤降级
    - needs_input：需要调用方补充会改变答案的信息
    - failed：没有可用结果
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"


class ErrorCode(StrEnum):
    """可跨 CLI、API 和 Dashboard 稳定传递的错误码。

    - invalid_request：请求字段不合法
    - ambiguous_request：歧义会改变答案
    - model_unavailable：模型不可用
    - structured_output_invalid：结构化输出不符合 schema
    - sql_policy_blocked：SQL 被策略阻断
    - query_budget_exceeded：查询超过预算
    - database_unavailable：数据库不可用
    - query_execution_failed：查询执行失败
    - internal_error：未分类的内部错误
    """

    INVALID_REQUEST = "invalid_request"
    AMBIGUOUS_REQUEST = "ambiguous_request"
    MODEL_UNAVAILABLE = "model_unavailable"
    STRUCTURED_OUTPUT_INVALID = "structured_output_invalid"
    SQL_POLICY_BLOCKED = "sql_policy_blocked"
    QUERY_BUDGET_EXCEEDED = "query_budget_exceeded"
    DATABASE_UNAVAILABLE = "database_unavailable"
    QUERY_EXECUTION_FAILED = "query_execution_failed"
    INTERNAL_ERROR = "internal_error"


class ErrorInfo(StrictModel):
    """可安全展示的错误信息，不包含密钥、SQL 全文或异常栈。

    - code：稳定错误码
    - stage：失败步骤名
    - message：给调用方的短说明
    - retryable：调用方可否原样重试
    - context：只放可序列化的补充字段
    """

    code: ErrorCode
    stage: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False
    context: dict[str, JsonValue] = Field(default_factory=dict)


class ArtifactKind(StrEnum):
    """可引用产物的种类。

    - csv：表格结果
    - json：结构化结果
    - sql：规范化 SQL
    - image：图片
    """

    CSV = "csv"
    JSON = "json"
    SQL = "sql"
    IMAGE = "image"


class ArtifactRef(StrictModel):
    """大结果或可下载文件的稳定引用。状态里只传本结构，不传文件正文。

    - artifact_id：稳定标识
    - kind：产物种类
    - uri：文件位置
    - content_hash：内容哈希
    - size_bytes：字节大小
    - created_at：创建时间
    """

    artifact_id: str = Field(min_length=1, max_length=128)
    kind: ArtifactKind
    uri: str = Field(min_length=1)
    content_hash: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=0)
    created_at: datetime


class EvidenceSource(StrictModel):
    """证据实际访问的一个数据源。

    - name：指标目录中的数据源名称
    - kind：数据源类型，table 表示原始表，view 表示视图
    """

    name: str = Field(min_length=1, max_length=128)
    kind: Literal["table", "view"]


class EvidenceEnvelope(StrictModel):
    """下游 Agent 唯一允许引用的数据事实。来源、质量和业务范围保持扁平。

    - evidence_id：证据标识
    - metric_ids：指标标识，至少一个
    - grain：结果粒度
    - scope：业务过滤范围
    - units：指标单位
    - columns：结果列名
    - preview：可放入图状态的小样本
    - returned_row_count：系统预算内实际保留的结果行数
    - truncated：查询结果是否被系统行数上限截断
    - sources：实际访问的数据源及其类型
    - data_snapshot：数据快照版本
    - executed_at：执行时间
    - artifacts：完整结果引用
    - warnings：质量提示
    """

    evidence_id: str = Field(min_length=1, max_length=128)
    metric_ids: tuple[str, ...] = Field(min_length=1)
    grain: tuple[str, ...] = ()
    scope: dict[str, JsonValue] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    columns: tuple[str, ...] = ()
    preview: tuple[dict[str, JsonValue], ...] = ()
    returned_row_count: int = Field(ge=0)
    truncated: bool = False
    sources: tuple[EvidenceSource, ...] = ()
    data_snapshot: str = Field(min_length=1, max_length=128)
    executed_at: datetime
    artifacts: tuple[ArtifactRef, ...] = ()
    warnings: tuple[str, ...] = ()


ResultT = TypeVar("ResultT")


class AgentResult(StrictModel, Generic[ResultT]):
    """所有专业 Agent 的统一返回外壳。

    - status：终态
    - value：该 Agent 的业务结果，类型由调用方参数决定
    - error：可展示错误
    - warnings：不改变终态的提示
    """

    status: AgentStatus
    value: ResultT | None = None
    error: ErrorInfo | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> AgentResult[ResultT]:
        """按终态约束 ``value`` 与 ``error`` 是否成对出现。

        输入：
        - status：终态
        - value：业务结果
        - error：可展示错误

        约束：
        - success：必须有 value，且 error 为空
        - failed：必须有 error
        - needs_input：必须有 value，用来携带澄清内容
        - partial：本步骤不额外限制

        输出：
        - 同一实例：违反时抛 ``ValueError``
        """
        if self.status == AgentStatus.SUCCESS:
            if self.value is None:
                raise ValueError("success 状态必须包含 value")
            if self.error is not None:
                raise ValueError("success 状态不能包含 error")

        if self.status == AgentStatus.FAILED and self.error is None:
            raise ValueError("failed 状态必须包含 error")

        if self.status == AgentStatus.NEEDS_INPUT and self.value is None:
            raise ValueError("needs_input 状态必须包含澄清信息")

        return self
