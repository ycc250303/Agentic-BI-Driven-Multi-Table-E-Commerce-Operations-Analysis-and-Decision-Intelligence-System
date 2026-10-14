"""数据分析 Agent 的确定性 LangGraph 工作流。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict, TypeVar, cast
from uuid import uuid4

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, ValidationError

from agentic_bi.agents.analysis.schemas import (
    AnalysisClaim,
    AnalysisOutput,
    AnalysisRequest,
    AnalysisResult,
    AnalysisSemanticSpec,
    QuerySnapshot,
    SqlDraft,
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
from agentic_bi.data.sql_guard import SqlGuard, SqlPolicyError
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
    - query_snapshot：执行后的小样本和产物引用
    - evidence：可供下游引用的数据事实
    - repair_attempts：已经用掉的 SQL 修复次数
    - repair_feedback：下一次生成可见的短反馈
    - result：提前结束或最终返回的结果
    """

    request: AnalysisRequest
    semantic_spec: AnalysisSemanticSpec
    sql_draft: SqlDraft
    query_snapshot: QuerySnapshot
    evidence: EvidenceEnvelope
    repair_attempts: int
    repair_feedback: str
    result: AnalysisResult


def build_analysis_graph() -> CompiledStateGraph[
    AnalysisState,
    AnalysisContext,
    AnalysisInput,
    AnalysisGraphOutput,
]:
    """编译解释、生成、执行、证据和摘要五步。

    输入：
    - 无

    约束：
    - 澄清或失败写入 result 后直接结束
    - 校验失败且仍可修复时回到 SQL 生成
    - 查询成功后才构建证据并摘要

    输出：
    - 已编译的图：输入为 request，输出为 result
    """
    builder = StateGraph(
        AnalysisState,
        context_schema=AnalysisContext,
        input_schema=AnalysisInput,
        output_schema=AnalysisGraphOutput,
    )
    builder.add_node("interpret_request", _interpret_request)
    builder.add_node("generate_sql", _generate_sql)
    builder.add_node("validate_and_execute", _validate_and_execute)
    builder.add_node("build_evidence", _build_evidence)
    builder.add_node("summarize", _summarize)

    builder.add_edge(START, "interpret_request")
    builder.add_conditional_edges(
        "interpret_request",
        _after_interpret,
        {"generate_sql": "generate_sql", "end": END},
    )
    builder.add_conditional_edges(
        "generate_sql",
        _after_generate,
        {"validate_and_execute": "validate_and_execute", "end": END},
    )
    builder.add_conditional_edges(
        "validate_and_execute",
        _after_execute,
        {
            "generate_sql": "generate_sql",
            "build_evidence": "build_evidence",
            "end": END,
        },
    )
    builder.add_edge("build_evidence", "summarize")
    builder.add_edge("summarize", END)
    return builder.compile()


def _interpret_request(
    state: AnalysisState,
    *,
    runtime: Runtime[AnalysisContext],
) -> AnalysisState:
    """生成并校验与 SQL 无关的业务语义。

    输入：
    - request：查数任务；已带 semantic_spec 时跳过模型
    - metrics：校验指标、维度、过滤字段和排序字段

    约束：
    - 会改变答案的歧义不生成 SQL，改为向调用方提问
    - 指标目录拒绝的语义不可修复

    输出：
    - semantic_spec：通过校验且没有歧义
    - result：待澄清或失败
    """
    request = state["request"]
    metrics = runtime.context.metrics

    try:
        semantic_spec = request.semantic_spec or _invoke(
            runtime,
            prompt_name="analysis/interpret",
            variables={
                "locale": request.locale,
                "metric_context": metrics.render_metric_context(),
                "question": request.question,
            },
            schema=AnalysisSemanticSpec,
            run_name="analysis.interpret",
        )
        metrics.validate_intent(
            metric_ids=semantic_spec.metric_ids,
            dimensions=semantic_spec.dimensions,
            filter_fields=(item.field for item in semantic_spec.filters),
            sort_by=semantic_spec.sort_by,
        )
    except (ValidationError, TypeError, ValueError) as exc:
        return _fail(
            request,
            code=ErrorCode.STRUCTURED_OUTPUT_INVALID,
            stage="interpret_request",
            message=_safe_message(exc, "数据分析语义无法通过指标目录校验"),
        )
    except Exception:
        return _fail(
            request,
            code=ErrorCode.MODEL_UNAVAILABLE,
            stage="interpret_request",
            message="语义解析模型暂时不可用",
            retryable=True,
        )

    if semantic_spec.ambiguities:
        return {
            "semantic_spec": semantic_spec,
            "result": AnalysisResult(
                status=AgentStatus.NEEDS_INPUT,
                value=AnalysisOutput(
                    task_id=request.task_id,
                    intent=semantic_spec,
                    clarification_questions=_clarification_questions(semantic_spec.ambiguities),
                ),
            ),
        }

    return {"semantic_spec": semantic_spec, "repair_attempts": 0, "repair_feedback": ""}


def _generate_sql(
    state: AnalysisState,
    *,
    runtime: Runtime[AnalysisContext],
) -> AnalysisState:
    """依据确认语义和最小 Schema 上下文生成候选 SQL。

    输入：
    - request：原始问题
    - semantic_spec：已确认的业务语义
    - repair_feedback：上一轮校验失败的短说明；首次为空

    输出：
    - sql_draft：一条尚未执行的候选查询
    - result：模型不可用时的失败
    """
    request = state["request"]
    semantic_spec = state["semantic_spec"]

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
                ),
                "repair_feedback": state.get("repair_feedback") or "首次生成，无反馈。",
            },
            schema=SqlDraft,
            run_name="analysis.generate_sql",
        )
    except Exception:
        return _fail(
            request,
            code=ErrorCode.MODEL_UNAVAILABLE,
            stage="generate_sql",
            message="SQL 生成模型暂时不可用",
            retryable=True,
        )

    return {"sql_draft": draft, "repair_feedback": ""}


def _validate_and_execute(
    state: AnalysisState,
    *,
    runtime: Runtime[AnalysisContext],
) -> AnalysisState:
    """完成 AST、EXPLAIN、只读执行、形态校验和产物写入。

    输入：
    - semantic_spec：用来限定数据源和核对结果列
    - sql_draft：候选 SQL

    约束：
    - 策略或执行错误在修复次数内回到生成
    - EXPLAIN 文案含“超过预算”时使用查询预算错误码
    - 数据库不可用、硬预算和产物写入失败不再改 SQL

    输出：
    - query_snapshot：预览、指纹和产物引用
    - repair_feedback：可修复时给下一轮生成
    - result：不可修复时的失败
    """
    request = state["request"]
    semantic_spec = state["semantic_spec"]
    deps = runtime.context
    allowed_sources = deps.metrics.allowed_sources(
        metric_ids=semantic_spec.metric_ids,
        dimensions=semantic_spec.dimensions,
    )

    try:
        validated = deps.sql_guard.validate(
            state["sql_draft"].sql,
            allowed_sources=allowed_sources,
            maximum_rows=deps.settings.sql_max_rows,
        )
        plan = deps.database.explain(validated.sql)
        deps.sql_guard.validate_plan(
            estimated_rows=plan.estimated_rows,
            sources=validated.sources,
        )
        execution = deps.database.execute(validated.sql)
        deps.metrics.validate_result_columns(
            columns=execution.columns,
            metric_ids=semantic_spec.metric_ids,
            dimensions=semantic_spec.dimensions,
        )
        snapshot = QuerySnapshot(
            columns=execution.columns,
            preview=execution.rows[: deps.settings.evidence_preview_rows],
            row_count=execution.row_count,
            truncated=execution.truncated,
            source_names=validated.sources,
            sql_fingerprint=validated.fingerprint,
            data_snapshot=execution.data_snapshot,
            executed_at=datetime.now(UTC),
            execution_time_ms=execution.execution_time_ms,
            artifacts=(
                deps.store.write_csv(
                    task_id=request.task_id,
                    columns=execution.columns,
                    rows=execution.rows,
                ),
                deps.store.write_sql(task_id=request.task_id, sql=validated.sql),
            ),
            warnings=_execution_warnings(
                truncated=execution.truncated,
                maximum_rows=deps.settings.sql_max_rows,
                estimated_rows=plan.estimated_rows,
            ),
        )
    except SqlPolicyError as exc:
        code = (
            ErrorCode.QUERY_BUDGET_EXCEEDED
            if "超过预算" in str(exc)
            else ErrorCode.SQL_POLICY_BLOCKED
        )
        return _repair_or_fail(
            state,
            runtime=runtime,
            code=code,
            message=str(exc),
            retryable=exc.retryable,
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
        return _fail(
            request,
            code=ErrorCode.QUERY_BUDGET_EXCEEDED,
            stage="validate_and_execute",
            message=str(exc),
        )
    except DatabaseUnavailableError:
        return _fail(
            request,
            code=ErrorCode.DATABASE_UNAVAILABLE,
            stage="validate_and_execute",
            message="只读数据库暂时不可用",
            retryable=True,
        )
    except OSError:
        return _fail(
            request,
            code=ErrorCode.INTERNAL_ERROR,
            stage="validate_and_execute",
            message="查询成功，但结果 Artifact 写入失败",
            retryable=True,
        )

    return {"query_snapshot": snapshot}


def _build_evidence(
    state: AnalysisState,
    *,
    runtime: Runtime[AnalysisContext],
) -> AnalysisState:
    """把执行快照提升为可供下游引用的 Evidence。

    输入：
    - semantic_spec：指标、维度、过滤和排序
    - query_snapshot：预览、来源和产物引用

    约束：
    - 结果粒度沿用分组维度
    - 范围只保留过滤、时间和结果形态，不放 SQL 全文

    输出：
    - evidence：一条带稳定标识的数据事实
    """
    semantic_spec = state["semantic_spec"]
    snapshot = state["query_snapshot"]
    metrics = runtime.context.metrics
    source_tables, source_views = metrics.source_kinds(snapshot.source_names)
    time_range = semantic_spec.time_range
    evidence = EvidenceEnvelope(
        evidence_id=f"ev-{uuid4().hex}",
        metric_ids=semantic_spec.metric_ids,
        dimensions=semantic_spec.dimensions,
        grain=semantic_spec.dimensions,
        scope={
            "filters": [item.model_dump(mode="json") for item in semantic_spec.filters],
            "time_range": None if time_range is None else time_range.model_dump(mode="json"),
            "operation": semantic_spec.operation.value,
            "sort_by": semantic_spec.sort_by,
            "sort_direction": semantic_spec.sort_direction,
            "limit": semantic_spec.limit,
        },
        units=metrics.units_for(semantic_spec.metric_ids),
        columns=snapshot.columns,
        preview=snapshot.preview,
        row_count=snapshot.row_count,
        truncated=snapshot.truncated,
        source_tables=source_tables,
        source_views=source_views,
        sql_fingerprint=snapshot.sql_fingerprint,
        data_snapshot=snapshot.data_snapshot,
        executed_at=snapshot.executed_at,
        execution_time_ms=snapshot.execution_time_ms,
        artifacts=snapshot.artifacts,
        warnings=snapshot.warnings,
    )
    return {"evidence": evidence}


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
    semantic_spec = state["semantic_spec"]
    evidence = state["evidence"]
    if evidence.row_count == 0:
        return {
            "result": _completed(
                _output(
                    request,
                    semantic_spec,
                    evidence,
                    headline="在给定指标口径和过滤范围内未查询到数据。",
                    limitations=evidence.warnings,
                ),
                warnings=evidence.warnings,
            )
        }

    try:
        summary = _invoke(
            runtime,
            prompt_name="analysis/summarize",
            variables={
                "locale": request.locale,
                "question": request.question,
                "evidence": evidence.model_dump_json(indent=2),
            },
            schema=SummaryDraft,
            run_name="analysis.summarize",
        )
        output = _output(
            request,
            semantic_spec,
            evidence,
            headline=summary.headline,
            claims=tuple(
                AnalysisClaim(evidence_id=claim.evidence_id, text=claim.text)
                for claim in summary.claims
            ),
            limitations=summary.limitations + evidence.warnings,
        )
        return {"result": _completed(output, warnings=evidence.warnings)}
    except Exception:
        output = _output(
            request,
            semantic_spec,
            evidence,
            headline="数据查询与证据构建已完成，但自然语言总结生成失败。",
            limitations=evidence.warnings,
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
                warnings=evidence.warnings,
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
) -> AnalysisState:
    """在修复次数内回到 SQL 生成，否则终止。

    输入：
    - repair_attempts：已经用掉的次数
    - code：本次失败的稳定错误码
    - message：给修复节点或调用方的短说明
    - retryable：本次错误是否允许再生成

    约束：
    - 次数达到 sql_max_repair_attempts 后不再修复
    - 不可修复的错误立即终止

    输出：
    - repair_feedback：下一轮生成可见的失败说明
    - result：终止时的失败结果
    """
    attempts = state.get("repair_attempts", 0)
    maximum = runtime.context.settings.sql_max_repair_attempts
    if retryable and attempts < maximum:
        return {
            "repair_attempts": attempts + 1,
            "repair_feedback": (
                f"第 {attempts + 1} 次校验失败：{message}。请重新生成完整 SQL，不要只返回补丁。"
            ),
        }

    return _fail(
        state["request"],
        code=code,
        stage="validate_and_execute",
        message=message,
        context={"repair_attempts": attempts, "maximum_repair_attempts": maximum},
    )


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
    semantic_spec: AnalysisSemanticSpec,
    evidence: EvidenceEnvelope,
    *,
    headline: str,
    claims: tuple[AnalysisClaim, ...] = (),
    limitations: tuple[str, ...] = (),
) -> AnalysisOutput:
    """组装一次成功路径上的公开输出。

    输入：
    - request：回传任务号
    - semantic_spec：最终采用的语义
    - evidence：唯一可引用的数据事实
    - headline：一句话结论
    - claims：必须引用该证据的事实
    - limitations：口径、截断或空结果说明

    输出：
    - 公开输出：证据固定为这一条
    """
    return AnalysisOutput(
        task_id=request.task_id,
        intent=semantic_spec,
        evidences=(evidence,),
        headline=headline,
        claims=claims,
        limitations=limitations,
    )


def _completed(
    output: AnalysisOutput,
    *,
    warnings: tuple[str, ...],
) -> AnalysisResult:
    """把已有证据的输出标成成功。

    输入：
    - output：公开业务结果
    - warnings：不改变终态的提示

    输出：
    - 成功结果：不带 error
    """
    return AnalysisResult(status=AgentStatus.SUCCESS, value=output, warnings=warnings)


def _execution_warnings(
    *,
    truncated: bool,
    maximum_rows: int,
    estimated_rows: int | None,
) -> tuple[str, ...]:
    """收集不阻断成功的执行提示。

    输入：
    - truncated：结果是否被行数上限截断
    - maximum_rows：系统允许保留的最大行数
    - estimated_rows：EXPLAIN 估算扫描行数，可空

    输出：
    - 提示：截断或缺少扫描估算时才有内容
    """
    warnings: list[str] = []
    if truncated:
        warnings.append(f"结果超过 {maximum_rows} 行，Artifact 仅保留系统允许的最大行数。")
    if estimated_rows is None:
        warnings.append("EXPLAIN 未返回可识别的扫描行数估算。")
    return tuple(warnings)


def _clarification_questions(ambiguities: tuple[str, ...]) -> tuple[str, ...]:
    """把歧义整理成向调用方提出的问题。

    输入：
    - ambiguities：会改变答案、尚未澄清的点

    输出：
    - 问题：已有问号的原文保留，其余补上“请确认”
    """
    return tuple(
        value if value.endswith(("？", "?")) else f"请确认：{value}" for value in ambiguities
    )


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


def _after_interpret(state: AnalysisState) -> Literal["generate_sql", "end"]:
    """语义已落成终态时结束，否则生成 SQL。

    输入：
    - state：解释节点写回后的图状态

    输出：
    - end：已有澄清或失败结果
    - generate_sql：语义通过且没有歧义
    """
    return "end" if "result" in state else "generate_sql"


def _after_generate(state: AnalysisState) -> Literal["validate_and_execute", "end"]:
    """SQL 已落成终态时结束，否则进入校验执行。

    输入：
    - state：生成节点写回后的图状态

    输出：
    - end：模型不可用
    - validate_and_execute：已有候选 SQL
    """
    return "end" if "result" in state else "validate_and_execute"


def _after_execute(
    state: AnalysisState,
) -> Literal["generate_sql", "build_evidence", "end"]:
    """执行结束后决定修复、出证据或终止。

    输入：
    - state：校验执行节点写回后的图状态

    约束：
    - 已有终态则结束
    - 已有查询快照则构建证据
    - 两者都没有则回到 SQL 生成

    输出：
    - end：失败且不再修复
    - build_evidence：查询已成功
    - generate_sql：本次失败但仍可修复
    """
    if "result" in state:
        return "end"
    if "query_snapshot" in state:
        return "build_evidence"
    return "generate_sql"
