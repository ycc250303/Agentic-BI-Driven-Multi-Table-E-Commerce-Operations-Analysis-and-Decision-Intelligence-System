from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from agents.coordinator_agent.orchestration.adapters import (
    build_analysis_result_from_sql_pipeline,
    merge_sql_runs,
)
from agents.coordinator_agent.orchestration.decomposer import (
    LLM_STRUCTURED_FALLBACK,
    decompose_query,
    decompose_to_state_patch,
)
from agents.coordinator_agent.orchestration.guardrails import is_off_topic_query, off_topic_state_patch
from agents.coordinator_agent.orchestration.replanner import apply_replan_decision, plan_recovery_queries
from agents.coordinator_agent.orchestration.router import (
    LLM_STRUCTURED_FALLBACK as ROUTE_LLM_FALLBACK,
    choose_next_agent,
)
from agents.coordinator_agent.state import AgentState
from agents.coordinator_agent.orchestration.synthesizer import synthesize_final_answer
from agents.coordinator_agent.events.tracing import TraceCollector
from agents.coordinator_agent.orchestration.upstream_ensure import ensure_upstream_payloads
from agents.decision_agent.run import run_decision_state
from agents.nlp_agent.run import ReviewInsightAgent
from agents.sql_agent.run import run_sql_pipeline_with_feedback


def _append_warning(state: AgentState, message: str) -> list[str]:
    warnings = list(state.get("warnings") or [])
    if message not in warnings:
        warnings.append(message)
    return warnings


def _append_log(state: AgentState, entry: dict[str, Any]) -> list[dict[str, Any]]:
    log = list(state.get("execution_log") or [])
    log.append(entry)
    return log


def _mark_done(state: AgentState, agent: str) -> dict[str, bool]:
    done = dict(state.get("agents_done") or {})
    done[agent] = True
    return done


def _commit(state: AgentState, agent: str, **patch: Any) -> AgentState:
    """专家产物写入全局 state，并标记该 Agent 完成。"""
    return {**state, **patch, "agents_done": _mark_done(state, agent)}


def _emit_trace(
    trace_collector: TraceCollector | None,
    *,
    agent: str,
    step: str,
    kind: str,
    title: str,
    summary: str,
    payload: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit a trace event to the trace collector."""
    if trace_collector is None:
        return
    trace_collector.emit(
        agent=agent,
        step=step,
        kind=kind,
        title=title,
        summary=summary,
        payload=payload,
        metadata=metadata,
    )


def decompose_node(
    state: AgentState,
    *,
    model=None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    """本轮只规划一次：识别意图、列出建议专长，写入 state；不在这里执行子 Agent。"""
    user_query = str(state.get("user_query") or state.get("question") or "").strip()
    if not user_query:
        _emit_trace(
            trace_collector,
            agent="coordinator_agent",
            step="decompose",
            kind="warning",
            title="问题分解跳过",
            summary="缺少 user_query，无法分解问题。",
        )
        return {
            **state,
            "warnings": _append_warning(state, "缺少 user_query，无法分解问题。"),
            "next_agent": "synthesize",
        }
    if is_off_topic_query(user_query):
        _emit_trace(
            trace_collector,
            agent="coordinator_agent",
            step="decompose",
            kind="planning",
            title="问题越界",
            summary="问题不属于 Olist 电商 BI 分析范围，进入拒答汇总。",
        )
        return {**state, **off_topic_state_patch(user_query)}
    result = decompose_query(user_query, model=model)
    if result.off_topic:
        _emit_trace(
            trace_collector,
            agent="coordinator_agent",
            step="decompose",
            kind="planning",
            title="问题越界",
            summary="分解器判断问题越界，进入拒答汇总。",
        )
        return {**state, **off_topic_state_patch(user_query)}

    # 将分解结果应用到状态中
    patch = decompose_to_state_patch(user_query, result)
    next_state: AgentState = {**state, **patch}
    if LLM_STRUCTURED_FALLBACK in (result.reasoning or ""):
        # 如果分解结果中包含 LLM_STRUCTURED_FALLBACK，则添加警告
        next_state["warnings"] = _append_warning(
            next_state,
            result.reasoning.split("；", 1)[0],
        )
    _emit_trace(
        trace_collector,
        agent="coordinator_agent",
        step="decompose",
        kind="planning",
        title="问题分解完成",
        summary=(
            f"识别 intent={result.intent}，拆分 {len(result.sub_questions)} 个子问题，"
            f"建议调度：{' → '.join(result.suggested_agents)}。"
        ),
        payload=result.model_dump(),
    )
    return next_state


def orchestrator_node(
    state: AgentState,
    *,
    model=None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    """执行循环枢纽：按当前进度每次只选下一个专长或汇总；不是按规划清单逐步弹出。"""
    if state.get("off_topic"):
        iterations = int(state.get("orchestrator_iterations") or 0) + 1
        _emit_trace(
            trace_collector,
            agent="coordinator_agent",
            step="route_next",
            kind="routing",
            title="路由到最终汇总",
            summary="off_topic，跳过子 Agent。",
            metadata={"next_agent": "synthesize", "iteration": iterations},
        )
        return {
            **state,
            "orchestrator_iterations": iterations,
            "next_agent": "synthesize",
            "execution_log": _append_log(
                state,
                {
                    "step": iterations,
                    "next_agent": "synthesize",
                    "reasoning": "off_topic，跳过子 Agent",
                },
            ),
        }
    # 计划恢复查询
    replan = plan_recovery_queries(state, model=model)
    if replan.should_replan:
        # 应用恢复查询决策
        state = {**state, **apply_replan_decision(state, replan)}
        _emit_trace(
            trace_collector,
            agent="coordinator_agent",
            step="replan",
            kind="planning",
            title="触发补充数据规划",
            summary=replan.reason,
            payload=replan.model_dump(mode="json"),
        )

    iterations = int(state.get("orchestrator_iterations") or 0) + 1
    # 选择下一个代理
    decision = choose_next_agent(
        {**state, "orchestrator_iterations": iterations},
        model=model,
    )
    _emit_trace(
        trace_collector,
        agent="coordinator_agent",
        step="route_next",
        kind="routing",
        title=f"路由到 {decision.next_agent}",
        summary=decision.reasoning,
        metadata={"next_agent": decision.next_agent, "iteration": iterations},
    )
    # 添加日志
    log = _append_log(
        state,
        {
            "step": iterations,
            "next_agent": decision.next_agent,
            "reasoning": decision.reasoning,
        },
    )
    # 更新状态
    next_state: AgentState = {
        **state,
        "orchestrator_iterations": iterations,
        "next_agent": decision.next_agent,
        "execution_log": log,
    }
    if ROUTE_LLM_FALLBACK in (decision.reasoning or ""):
        # 如果路由结果中包含 ROUTE_LLM_FALLBACK，则添加警告
        next_state["warnings"] = _append_warning(
            next_state,
            decision.reasoning.split("；", 1)[0],
        )
    return next_state


def data_analysis_node(
    state: AgentState,
    *,
    model=None,
    on_tool_end: Callable[[str, str], None] | None = None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    # 获取子问题列表
    sub_questions = state.get("sub_questions") or [str(state.get("user_query") or "")]
    # 获取 SQL 运行结果
    sql_runs = list(state.get("sql_runs") or [])
    # 获取当前 SQL 运行索引
    idx = len(sql_runs)
    if idx >= len(sub_questions):
        # 如果当前 SQL 运行索引大于等于子问题数量，则提交状态
        return _commit(state, "data_analysis")

    # 获取当前子问题
    question = sub_questions[idx]
    # 运行 SQL 流水线
    sql_out = run_sql_pipeline_with_feedback(question, model=model, on_tool_end=on_tool_end)
    # 构建分析结果
    analysis = build_analysis_result_from_sql_pipeline(
        user_query=question,
        sql_pipeline=sql_out,
    )
    _emit_trace(
        trace_collector,
        agent="data_analysis_agent",
        step="analysis_result",
        kind="agent_result",
        title="数据分析结果整理完成",
        summary=str(analysis.get("business_summary") or analysis.get("summary_text") or ""),
        metadata={"question": question, "index": idx},
    )
    # 出图主要读 execute_sql_json（CSV 路径）；analysis_result 给套件规划当摘要
    sql_runs.append(
        {
            "question": question,
            "index": idx,
            "sql_pipeline": sql_out,
            "analysis_result": analysis,
            "execute_sql_json": sql_out.get("execute_sql_json", ""),
        }
    )
    # 合并 SQL 运行结果
    merged = merge_sql_runs(sql_runs)
    # 更新状态
    next_state: AgentState = {
        **state,
        "sql_runs": sql_runs,
        "analysis_result": merged,
        "sql_pipeline": sql_out,
        "rewrite_json": sql_out.get("rewrite_json", ""),
        "generate_sql_json": sql_out.get("generate_sql_json", ""),
        "execute_sql_json": sql_out.get("execute_sql_json", ""),
    }
    exec_payload = json.loads(sql_out.get("execute_sql_json") or "{}")
    if not exec_payload.get("ok"):
        # 如果 SQL 运行结果中包含错误，则添加警告
        next_state["warnings"] = _append_warning(
            next_state,
            f"子问题「{question}」SQL 未完全成功：{exec_payload.get('error_message') or '未知'}",
        )

    if len(sql_runs) >= len(sub_questions):
        return _commit(next_state, "data_analysis")
    return next_state


def visualization_node(
    state: AgentState,
    *,
    model=None,
    on_tool_end: Callable[[str, str], None] | None = None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    """协调器出图节点：消费已有 sql_runs / 评论洞察，写出 visualization_result。

    不在此重写 SQL、不画图。真正规划与渲染在
    ``agents.viz_agent.intelligent_viz.run_intelligent_visualization``。
    无 sql_runs 时直接 skipped（查数未完成不能出图）。
    """
    from agents.viz_agent.intelligent_viz import run_intelligent_visualization

    sql_runs = state.get("sql_runs") or []
    if not sql_runs:
        _emit_trace(
            trace_collector,
            agent="visualization_agent",
            step="visualization",
            kind="agent_result",
            title="可视化跳过",
            summary="尚无 SQL 分析结果，跳过可视化。",
        )
        return _commit(
            state,
            "visualization",
            visualization_result={
                "skipped": True,
                "summary_text": "尚无 SQL 分析结果，跳过可视化。",
                "charts": [],
            },
        )

    # 运行智能可视化
    viz_result = run_intelligent_visualization(
        user_query=str(state.get("user_query") or ""),
        intent=str(state.get("intent") or "descriptive"),
        sql_runs=sql_runs,
        review_insights=state.get("review_insights") or state.get("nlp_result"),
        model=model,
        on_tool_end=on_tool_end,
    )

    patch: dict[str, Any] = {}
    if viz_result.get("forecast_result") and not state.get("forecast_result"):
        patch["forecast_result"] = viz_result["forecast_result"]
    if not state.get("forecast_result") and not patch.get("forecast_result"):
        from agents.decision_agent.tools.forecast_from_analysis import enrich_forecast_from_state

        merged_for_fc = {**state, **patch}
        fc_patch = enrich_forecast_from_state(merged_for_fc)
        if fc_patch.get("forecast_result"):
            patch["forecast_result"] = fc_patch["forecast_result"]

    charts = viz_result.get("charts") or []
    _emit_trace(
        trace_collector,
        agent="visualization_agent",
        step="visualization",
        kind="agent_result",
        title="可视化 Agent 完成",
        summary=str(viz_result.get("summary_text") or f"生成/规划 {len(charts)} 个图表结果。"),
        metadata={"chart_count": len(charts)},
    )

    return _commit(state, "visualization", visualization_result=viz_result, **patch)


def nlp_node(
    state: AgentState,
    *,
    model=None,
    on_tool_end: Callable[[str, str], None] | None = None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    """评论洞察 Agent 节点：消费已有 sql_runs / 评论洞察，写出 review_insights。"""
    # NLP 在线路径不调 LLM；保留 model 以匹配图节点统一调用约定。
    _ = model

    insights = state.get("review_insights") or ReviewInsightAgent().run(on_tool_end=on_tool_end)
    _emit_trace(
        trace_collector,
        agent="nlp_agent",
        step="review_insights",
        kind="agent_result",
        title="评论洞察 Agent 完成",
        summary=str(insights.get("summary") or insights.get("summary_text") or "已完成评论主题、情感与词云数据整理。"),
    )
    return _commit(state, "nlp", review_insights=insights, nlp_result=insights)


def decision_node(
    state: AgentState,
    *,
    model=None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    """决策 Agent 节点：消费已有 review_insights / 决策结果，写出 decision_result。"""
    # 决策内部自行取模型；保留 model 以匹配图节点统一调用约定。
    _ = model
    # 确保上游负载
    working = {**state, **ensure_upstream_payloads(state)}
    # 运行决策状态
    out = run_decision_state(working)
    decision = out.get("decision_result") or {}
    what_if = decision.get("what_if_result") or {}
    quality = decision.get("quality_report") or {}
    _emit_trace(
        trace_collector,
        agent="decision_agent",
        step="compose_final_answer",
        kind="agent_result",
        title="决策 Agent 完成",
        summary=str(decision.get("narrative_answer") or out.get("final_answer") or ""),
        metadata={
            "action_count": len(decision.get("action_plan") or []),
            "decision_theme": decision.get("decision_theme"),
            "what_if_status": what_if.get("status"),
            "what_if_scenario": what_if.get("scenario_type"),
            "quality_score": quality.get("score"),
            "revision_count": decision.get("revision_count", 0),
        },
    )
    return _commit(out, "decision")


def synthesize_node(
    state: AgentState,
    *,
    model=None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    """最终回答节点：消费已有 state，写出 final_answer。"""

    if state.get("off_topic") and state.get("final_answer"):
        _emit_trace(
            trace_collector,
            agent="coordinator_agent",
            step="synthesize_answer",
            kind="final_answer",
            title="最终回答完成",
            summary=str(state.get("final_answer") or ""),
        )
        return _commit(state, "synthesize")
    # 生成最终回答
    answer, synth_warning = synthesize_final_answer(state, model=model)
    # 更新状态
    next_state: AgentState = _commit(state, "synthesize", final_answer=answer)
    if synth_warning:
        next_state["warnings"] = _append_warning(next_state, synth_warning)
    _emit_trace(
        trace_collector,
        agent="coordinator_agent",
        step="synthesize_answer",
        kind="final_answer",
        title="最终回答完成",
        summary=answer,
    )
    return next_state


def route_from_state(state: AgentState) -> str:
    nxt = str(state.get("next_agent") or "synthesize")
    allowed = {"data_analysis", "visualization", "nlp", "decision", "synthesize"}
    return nxt if nxt in allowed else "synthesize"
