"""数据分析 Agent 的确定性 LangGraph 工作流。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from typing import Any, Literal, TypedDict, TypeVar, cast
from uuid import uuid4

import sqlglot
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from agentic_bi.agents.analysis.schemas import (
    AnalysisClaim,
    AnalysisClarification,
    AnalysisInterpretation,
    AnalysisOutput,
    AnalysisRequest,
    AnalysisResult,
    AnalysisSemanticSpec,
    SqlDraft,
    SqlRepairState,
    SummaryDraft,
)
from agentic_bi.core.llm import ModelGateway
from agentic_bi.core.models import AgentStatus, ErrorCode, ErrorInfo, EvidenceEnvelope
from agentic_bi.core.prompts import render_prompt
from agentic_bi.core.settings import Settings
from agentic_bi.data.database import (
    DatabaseUnavailableError,
    QueryBudgetError,
    QueryExecutionError,
    ReadOnlyDatabase,
)
from agentic_bi.data.metrics import MetricCatalog
from agentic_bi.data.sql_guard import (
    SqlGuard,
    SqlPolicyError,
    SqlPolicyViolation,
)
from agentic_bi.data.store import Store

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """节点依赖。模型、数据库和产物存储不进入 checkpoint。

    - settings：超时、行数和修复次数等运行配置
    - models：结构化模型调用
    - metrics：指标目录与最小上下文
    - sql_guard：AST、白名单和扫描预算
    - database：只读 EXPLAIN 与执行
    - store：完整结果和规范化 SQL 的落盘
    """

    settings: Settings
    models: ModelGateway
    metrics: MetricCatalog
    sql_guard: SqlGuard
    database: ReadOnlyDatabase
    store: Store


class AnalysisInput(TypedDict):
    """图的公开输入。

    - request：一个已消解指代的查数任务
    """

    request: AnalysisRequest


class AnalysisGraphOutput(TypedDict):
    """图的公开输出。

    - result：成功、部分成功、待澄清或失败
    """

    result: AnalysisResult


class AnalysisState(TypedDict, total=False):
    """图内部状态。不保存模型、连接或完整查询结果，字段按节点逐步写入。

    - request：原始查数任务
    - semantic_spec：通过指标目录的业务语义
    - sql_draft：最近一次候选 SQL
    - evidence：可供下游引用的数据事实
    - repair：SQL 修复次数、反馈和上一条失败 SQL 的指纹
    - result：提前结束或最终返回的结果
    """

    request: AnalysisRequest
    semantic_spec: AnalysisSemanticSpec
    sql_draft: SqlDraft
    evidence: EvidenceEnvelope
    repair: SqlRepairState
    result: AnalysisResult


def build_analysis_graph() -> CompiledStateGraph[
    AnalysisState,
    AnalysisContext,
    AnalysisInput,
    AnalysisGraphOutput,
]:
    """编译解释、生成、校验执行和摘要四个节点。

    输入：
    - 无

    约束：
    - 澄清或失败写入 result 后直接结束
    - 校验失败且仍可修复时回到 SQL 生成
    - 校验执行节点完成产物写入和证据封装
    - 查询成功后才进入摘要

    输出：
    - 已编译的图：输入为 request，输出为 result
    """
    return _compile_analysis_graph()


def build_studio_graph() -> CompiledStateGraph[
    AnalysisState,
    AnalysisContext,
    AnalysisInput,
    AnalysisGraphOutput,
]:
    """给 Agent Server 编译同一张分析图，并绑定进程内依赖。

    输入：
    - 无

    约束：
    - 依赖由 ``create_analysis_context`` 在进程内构造，不进入 checkpoint
    - Studio 传入的 request 字典先校验成 ``AnalysisRequest``

    输出：
    - 已编译的图：输入为 request，输出为 result
    """
    from agentic_bi.agents.analysis.run import create_analysis_context

    context = create_analysis_context(Settings())
    return _compile_analysis_graph(bind=_bind_studio_node(context))


def _bind_studio_node(context: AnalysisContext) -> Callable[[Any], Any]:
    """返回把进程依赖写入 Runtime 的节点包装。

    输入：
    - context：进程内构造的节点依赖

    约束：
    - request 为字典时先校验成 ``AnalysisRequest``

    输出：
    - 包装函数：接收原节点，返回带依赖的节点
    """

    def bind(fn: Any) -> Any:
        @wraps(fn)
        def node(state: AnalysisState, *, runtime: Runtime[AnalysisContext]) -> Any:
            request: object = state.get("request")
            if isinstance(request, dict):
                state = cast(
                    AnalysisState,
                    {**state, "request": AnalysisRequest.model_validate(request)},
                )
            return fn(state, runtime=replace(runtime, context=context))

        return node

    return bind


def _compile_analysis_graph(
    *,
    bind: Callable[[Any], Any] | None = None,
) -> CompiledStateGraph[
    AnalysisState,
    AnalysisContext,
    AnalysisInput,
    AnalysisGraphOutput,
]:
    """按固定节点和边编译分析图。

    输入：
    - bind：节点包装；为空时直接使用原节点

    约束：
    - 澄清或失败写入 result 后直接结束
    - 校验失败且仍可修复时回到 SQL 生成
    - 校验执行节点完成产物写入和证据封装
    - 查询成功后才进入摘要
    - ``compile`` 不接收 checkpointer

    输出：
    - 已编译的图：输入为 request，输出为 result
    """

    def use(fn: Any) -> Any:
        if bind is None:
            return fn
        return bind(fn)

    builder = StateGraph(
        AnalysisState,
        context_schema=AnalysisContext,
        input_schema=AnalysisInput,
        output_schema=AnalysisGraphOutput,
    )
    builder.add_node("interpret_request", use(_interpret_request))
    builder.add_node("generate_sql", use(_generate_sql))
    builder.add_node("validate_and_execute", use(_validate_and_execute))
    builder.add_node("summarize", use(_summarize))
    builder.add_edge(START, "interpret_request")
    builder.add_edge("summarize", END)
    return builder.compile()


def _interpret_request(
    state: AnalysisState,
    *,
    runtime: Runtime[AnalysisContext],
) -> Command[Literal["generate_sql", "__end__"]]:
    """理解需求，生成并校验业务分析关注点。

    输入：
    - request：查数任务；已带 semantic_spec 时跳过模型
    - metrics：校验指标、维度、过滤字段和排序字段

    约束：
    - clarify 分支直接返回待补充，不进入指标目录校验
    - execute 分支必须通过指标目录校验

    输出：
    - semantic_spec：通过校验且没有歧义
    - result：待澄清或失败
    - goto：继续生成 SQL 或结束
    """
    request = state["request"]
    metrics = runtime.context.metrics

    try:
        interpretation: AnalysisSemanticSpec | AnalysisClarification
        if request.semantic_spec is not None:
            interpretation = request.semantic_spec
        else:
            interpreted = _invoke(
                runtime,
                prompt_name="analysis/interpret",
                variables={
                    "locale": request.locale,
                    "metric_context": metrics.render_metric_context(),
                    "question": request.question,
                },
                schema=AnalysisInterpretation,
                run_name="analysis.interpret",
            )
            interpretation = interpreted.interpretation
    except (ValidationError, TypeError, ValueError) as exc:
        return Command(
            update=_fail(
                request,
                code=ErrorCode.STRUCTURED_OUTPUT_INVALID,
                stage="interpret_request",
                message=_safe_message(exc, "数据分析语义无法通过指标目录校验"),
            ),
            goto="__end__",
        )
    except Exception:
        return Command(
            update=_fail(
                request,
                code=ErrorCode.MODEL_UNAVAILABLE,
                stage="interpret_request",
                message="语义解析模型暂时不可用",
                retryable=True,
            ),
            goto="__end__",
        )

    if isinstance(interpretation, AnalysisClarification):
        return Command(
            update={
                "result": AnalysisResult(
                    status=AgentStatus.NEEDS_INPUT,
                    value=AnalysisOutput(
                        task_id=request.task_id,
                        clarification=interpretation,
                    ),
                ),
            },
            goto="__end__",
        )

    semantic_spec = interpretation

    try:
        metrics.validate_intent(
            metric_ids=semantic_spec.metric_ids,
            dimensions=semantic_spec.dimensions,
            filter_fields=(item.field for item in semantic_spec.filters),
            sort_by=semantic_spec.sort_by,
        )
    except (TypeError, ValueError) as exc:
        return Command(
            update=_fail(
                request,
                code=ErrorCode.STRUCTURED_OUTPUT_INVALID,
                stage="interpret_request",
                message=_safe_message(exc, "数据分析语义无法通过指标目录校验"),
            ),
            goto="__end__",
        )

    return Command(
        update={
            "semantic_spec": semantic_spec,
            "repair": SqlRepairState(),
        },
        goto="generate_sql",
    )


def _generate_sql(
    state: AnalysisState,
    *,
    runtime: Runtime[AnalysisContext],
) -> Command[Literal["validate_and_execute", "__end__"]]:
    """依据确认语义和最小 Schema 上下文生成候选 SQL。

    输入：
    - request：原始问题
    - semantic_spec：已确认的业务语义
    - repair：上一轮失败信息；首次使用空状态

    输出：
    - sql_draft：一条尚未执行的候选查询
    - result：模型不可用时的失败
    - goto：继续校验执行或结束
    """
    request = state["request"]
    semantic_spec = state["semantic_spec"]
    repair = state.get("repair", SqlRepairState())

    try:
        draft = _invoke(
            runtime,
            prompt_name="analysis/generate_sql",
            variables={
                "question": request.question,
                "semantic_spec": semantic_spec.model_dump_json(indent=2),
                "schema_context": runtime.context.metrics.render_schema_context(
                    metric_ids=semantic_spec.metric_ids,
                    dimensions=semantic_spec.dimensions,
                    filter_fields=(item.field for item in semantic_spec.filters),
                ),
                "repair_feedback": repair.feedback or "首次生成，无反馈。",
            },
            schema=SqlDraft,
            run_name="analysis.generate_sql",
        )
    except Exception:
        return Command(
            update=_fail(
                request,
                code=ErrorCode.MODEL_UNAVAILABLE,
                stage="generate_sql",
                message="SQL 生成模型暂时不可用",
                retryable=True,
            ),
            goto="__end__",
        )

    draft_hash = _sql_hash(draft.sql)
    if repair.failed_sql_hash == draft_hash:
        error_code = ErrorCode(repair.error_code or ErrorCode.INTERNAL_ERROR.value)
        return Command(
            update=_fail(
                request,
                code=error_code,
                stage="generate_sql",
                message=repair.error_message or "SQL 修复没有产生新查询",
                context={
                    "repair_attempts": repair.attempts,
                    "maximum_repair_attempts": runtime.context.settings.sql_max_repair_attempts,
                    "reason": "repeated_sql",
                },
            ),
            goto="__end__",
        )

    return Command(
        update={
            "sql_draft": draft,
            "repair": repair.model_copy(update={"feedback": ""}),
        },
        goto="validate_and_execute",
    )


def _validate_and_execute(
    state: AnalysisState,
    *,
    runtime: Runtime[AnalysisContext],
) -> Command[Literal["generate_sql", "summarize", "__end__"]]:
    """完成 AST、EXPLAIN、只读执行、结果校验、产物写入和证据封装。

    输入：
    - semantic_spec：用来限定数据源和核对结果列
    - sql_draft：候选 SQL

    约束：
    - 策略或执行错误在修复次数内回到生成
    - EXPLAIN 文案含“超过预算”时使用查询预算错误码
    - 数据库不可用、硬预算和产物写入失败不再改 SQL

    输出：
    - evidence：业务范围、预览、来源和产物引用
    - repair：可修复时保存下一轮生成所需的失败信息
    - result：不可修复时的失败
    - goto：重新生成 SQL、继续摘要或结束
    """

    """校验执行"""
    request = state["request"]
    semantic_spec = state["semantic_spec"]
    deps = runtime.context
    allowed_sources = deps.metrics.allowed_sources(
        metric_ids=semantic_spec.metric_ids,
        dimensions=semantic_spec.dimensions,
        filter_fields=(item.field for item in semantic_spec.filters),
    )

    try:
        """校验 SQL"""
        validated = deps.sql_guard.validate(
            state["sql_draft"].sql,
            allowed_sources=allowed_sources,
            maximum_rows=deps.settings.sql_max_rows,
        )
        """EXPLAIN"""
        plan = deps.database.explain(validated.sql)
        """校验计划"""
        deps.sql_guard.validate_plan(
            estimated_rows=plan.estimated_rows,
            sources=validated.sources,
        )
        """执行"""
        execution = deps.database.execute(validated.sql)
        """校验结果列"""
        deps.metrics.validate_result_columns(
            columns=execution.columns,
            metric_ids=semantic_spec.metric_ids,
            dimensions=semantic_spec.dimensions,
        )
        """写入产物"""
        artifacts = (
            deps.store.write_csv(
                task_id=request.task_id,
                columns=execution.columns,
                rows=execution.rows,
            ),
            deps.store.write_sql(task_id=request.task_id, sql=validated.sql),
        )
        """构建证据"""
        time_range = semantic_spec.time_range
        evidence = EvidenceEnvelope(
            evidence_id=f"ev-{uuid4().hex}",
            metric_ids=semantic_spec.metric_ids,
            grain=semantic_spec.dimensions,
            scope={
                "filters": [item.model_dump(mode="json") for item in semantic_spec.filters],
                "time_range": None if time_range is None else time_range.model_dump(mode="json"),
                "operation": semantic_spec.operation.value,
                "sort_by": semantic_spec.sort_by,
                "sort_direction": semantic_spec.sort_direction,
                "limit": semantic_spec.limit,
            },
            units=deps.metrics.units_for(semantic_spec.metric_ids),
            columns=execution.columns,
            preview=execution.rows[: deps.settings.evidence_preview_rows],
            returned_row_count=execution.returned_row_count,
            truncated=execution.truncated,
            sources=deps.metrics.evidence_sources(validated.sources),
            data_snapshot=execution.data_snapshot,
            executed_at=datetime.now(UTC),
            artifacts=artifacts,
            warnings=_execution_warnings(estimated_rows=plan.estimated_rows),
        )
    except SqlPolicyError as exc:
        code = (
            ErrorCode.QUERY_BUDGET_EXCEEDED
            if exc.violation == SqlPolicyViolation.QUERY_BUDGET_EXCEEDED
            else ErrorCode.SQL_POLICY_BLOCKED
        )
        return _repair_or_fail(
            state,
            runtime=runtime,
            code=code,
            message=str(exc),
            retryable=exc.retryable,
            repair_feedback=exc.repair_feedback(),
        )
    except QueryExecutionError as exc:
        return _repair_or_fail(
            state,
            runtime=runtime,
            code=ErrorCode.QUERY_EXECUTION_FAILED,
            message=str(exc),
            retryable=exc.retryable,
        )
    except ValueError as exc:
        return _repair_or_fail(
            state,
            runtime=runtime,
            code=ErrorCode.STRUCTURED_OUTPUT_INVALID,
            message=_safe_message(exc, "SQL 结果形态与业务语义不一致"),
            retryable=True,
        )
    except QueryBudgetError as exc:
        return Command(
            update=_fail(
                request,
                code=ErrorCode.QUERY_BUDGET_EXCEEDED,
                stage="validate_and_execute",
                message=str(exc),
            ),
            goto="__end__",
        )
    except DatabaseUnavailableError:
        return Command(
            update=_fail(
                request,
                code=ErrorCode.DATABASE_UNAVAILABLE,
                stage="validate_and_execute",
                message="只读数据库暂时不可用",
                retryable=True,
            ),
            goto="__end__",
        )
    except OSError:
        return Command(
            update=_fail(
                request,
                code=ErrorCode.INTERNAL_ERROR,
                stage="validate_and_execute",
                message="查询成功，但结果 Artifact 写入失败",
                retryable=True,
            ),
            goto="__end__",
        )

    return Command(update={"evidence": evidence}, goto="summarize")


def _summarize(
    state: AnalysisState,
    *,
    runtime: Runtime[AnalysisContext],
) -> AnalysisState:
    """生成只引用 Evidence 的自然语言结论。

    输入：
    - request：原问题与语言
    - evidence：已封装的数据事实

    约束：
    - 空结果直接成功，不调用模型，也不改写成猜测
    - 摘要失败时保留证据，终态为部分成功

    输出：
    - result：成功或带可用证据的部分成功
    """
    request = state["request"]
    evidence = state["evidence"]
    if evidence.returned_row_count == 0:
        return {
            "result": _completed(
                _output(
                    request,
                    evidence,
                    headline="在给定指标口径和过滤范围内未查询到数据。",
                )
            )
        }

    try:
        summary = _invoke(
            runtime,
            prompt_name="analysis/summarize",
            variables={
                "locale": request.locale,
                "question": request.question,
                "evidence": _summary_evidence_json(evidence),
            },
            schema=SummaryDraft,
            run_name="analysis.summarize",
        )
        output = _output(
            request,
            evidence,
            headline=summary.headline,
            claims=summary.claims,
            limitations=summary.limitations,
        )
        return {"result": _completed(output)}
    except Exception:
        output = _output(
            request,
            evidence,
            headline="数据查询与证据构建已完成，但自然语言总结生成失败。",
        )
        return {
            "result": AnalysisResult(
                status=AgentStatus.PARTIAL,
                value=output,
                error=ErrorInfo(
                    code=ErrorCode.MODEL_UNAVAILABLE,
                    stage="summarize",
                    message="摘要模型暂时不可用，已返回可验证 Evidence",
                    retryable=True,
                ),
            )
        }


def _invoke(
    runtime: Runtime[AnalysisContext],
    *,
    prompt_name: str,
    variables: dict[str, Any],
    schema: type[SchemaT],
    run_name: str,
) -> SchemaT:
    """渲染一份 Prompt，并校验成指定结构。

    输入：
    - prompt_name：相对 config/prompts 的模板名
    - variables：模板占位符
    - schema：期望的结构化结果
    - run_name：子运行名称

    约束：
    - 父运行配置从当前 LangGraph 配置读取，不由节点参数传入

    输出：
    - schema 实例：渲染或模型调用失败时抛出原异常
    """
    prompt = render_prompt(
        prompt_name,
        variables,
        config_dir=runtime.context.settings.config_dir,
    )
    config = get_config()
    return runtime.context.models.invoke_structured(
        schema,
        [SystemMessage(content=prompt.content)],
        config=_child_config(config, run_name=run_name, prompt_version=prompt.version),
    )


def _repair_or_fail(
    state: AnalysisState,
    *,
    runtime: Runtime[AnalysisContext],
    code: ErrorCode,
    message: str,
    retryable: bool,
    repair_feedback: str | None = None,
) -> Command[Literal["generate_sql", "summarize", "__end__"]]:
    """在修复次数内回到 SQL 生成，否则终止。

    输入：
    - repair.attempts：已经用掉的次数
    - code：本次失败的稳定错误码
    - message：给修复节点或调用方的短说明
    - retryable：本次错误是否允许再生成
    - repair_feedback：包含稳定错误字段的修复说明；为空时使用 message

    约束：
    - 次数达到 sql_max_repair_attempts 后不再修复
    - 不可修复的错误立即终止

    输出：
    - repair：下一轮生成可见的失败说明和失败 SQL 指纹
    - result：终止时的失败结果
    - goto：重新生成 SQL 或结束
    """
    repair = state.get("repair", SqlRepairState())
    attempts = repair.attempts
    maximum = runtime.context.settings.sql_max_repair_attempts
    if retryable and attempts < maximum:
        details = repair_feedback or message
        feedback = f"第 {attempts + 1} 次校验失败：{details}。请重新生成完整 SQL，不要只返回补丁。"
        return Command(
            update={
                "repair": SqlRepairState(
                    attempts=attempts + 1,
                    feedback=feedback,
                    failed_sql_hash=_sql_hash(state["sql_draft"].sql),
                    error_code=code.value,
                    error_message=message,
                ),
            },
            goto="generate_sql",
        )

    return Command(
        update=_fail(
            state["request"],
            code=code,
            stage="validate_and_execute",
            message=message,
            context={"repair_attempts": attempts, "maximum_repair_attempts": maximum},
        ),
        goto="__end__",
    )


def _sql_hash(sql: str) -> str:
    """生成忽略格式、注释和标识符大小写的 SQL 指纹。

    输入：
    - sql：模型生成的候选 SQL

    输出：
    - SHA-256：SQL 无法解析时按压缩空白后的原文计算
    """
    try:
        expression = sqlglot.parse_one(sql, read="mysql")
        normalized = expression.sql(
            dialect="mysql",
            pretty=False,
            comments=False,
            normalize=True,
        )
    except sqlglot.errors.ParseError:
        normalized = " ".join(sql.split())
    return sha256(normalized.encode("utf-8")).hexdigest()


def _fail(
    request: AnalysisRequest,
    *,
    code: ErrorCode,
    stage: str,
    message: str,
    retryable: bool = False,
    context: dict[str, int | str | bool | None] | None = None,
) -> AnalysisState:
    """把稳定错误包成图的失败终态。

    输入：
    - request：用于关联任务，不把问题原文写入错误
    - code：稳定错误码
    - stage：失败节点名
    - message：给调用方的短说明
    - retryable：调用方可否原样重试
    - context：可序列化的补充字段

    输出：
    - result：没有业务结果的失败
    """
    return {
        "result": AnalysisResult(
            status=AgentStatus.FAILED,
            error=ErrorInfo(
                code=code,
                stage=stage,
                message=message,
                retryable=retryable,
                context=context or {},
            ),
        )
    }


def _output(
    request: AnalysisRequest,
    evidence: EvidenceEnvelope,
    *,
    headline: str,
    claims: tuple[AnalysisClaim, ...] = (),
    limitations: tuple[str, ...] = (),
) -> AnalysisOutput:
    """组装一次成功路径上的公开输出。

    输入：
    - request：回传任务号
    - evidence：唯一可引用的数据事实
    - headline：一句话结论
    - claims：必须引用该证据的事实
    - limitations：口径、截断或空结果说明

    输出：
    - 公开输出：证据固定为这一条
    """
    return AnalysisOutput(
        task_id=request.task_id,
        evidence=evidence,
        headline=headline,
        claims=claims,
        limitations=limitations,
    )


def _completed(output: AnalysisOutput) -> AnalysisResult:
    """把已有证据的输出标成成功。

    输入：
    - output：公开业务结果

    输出：
    - 成功结果：不带 error
    """
    return AnalysisResult(status=AgentStatus.SUCCESS, value=output)


def _summary_evidence_json(evidence: EvidenceEnvelope) -> str:
    """只向摘要模型提供回答问题所需的证据字段。

    输入：
    - evidence：完整业务证据

    输出：
    - JSON：不包含产物地址、来源审计、数据快照和执行时间
    """
    return evidence.model_dump_json(
        include={
            "evidence_id",
            "metric_ids",
            "grain",
            "scope",
            "units",
            "columns",
            "preview",
            "returned_row_count",
            "truncated",
            "warnings",
        },
        indent=2,
    )


def _execution_warnings(
    *,
    estimated_rows: int | None,
) -> tuple[str, ...]:
    """收集不阻断成功的执行提示。

    输入：
    - estimated_rows：EXPLAIN 估算扫描行数，可空

    输出：
    - 提示：缺少扫描估算时才有内容
    """
    warnings: list[str] = []
    if estimated_rows is None:
        warnings.append("EXPLAIN 未返回可识别的扫描行数估算。")
    return tuple(warnings)


def _child_config(
    config: RunnableConfig,
    *,
    run_name: str,
    prompt_version: str,
) -> RunnableConfig:
    """保留父级 callbacks，并补充子运行检索元数据。

    输入：
    - config：父运行配置
    - run_name：子运行名称
    - prompt_version：本次渲染的模板版本

    输出：
    - 子运行配置：metadata 增加 prompt_version
    """
    child = dict(config)
    metadata = dict(config.get("metadata") or {})
    metadata["prompt_version"] = prompt_version
    child["metadata"] = metadata
    child["run_name"] = run_name
    return cast(RunnableConfig, child)


def _safe_message(exc: Exception, fallback: str) -> str:
    """取可展示的短错误，避免把空异常交给调用方。

    输入：
    - exc：校验或结构化输出异常
    - fallback：原文为空时的兜底说明

    输出：
    - 短说明：去掉首尾空白，最长 500 字
    """
    message = str(exc).strip()
    return message[:500] if message else fallback
