from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agents.coordinator_agent.adapters import (
    build_analysis_result_from_sql_pipeline,
    merge_sql_runs,
)
from agents.coordinator_agent.decomposer import decompose_query, decompose_to_state_patch
from agents.coordinator_agent.guardrails import is_off_topic_query, off_topic_state_patch
from agents.coordinator_agent.router import choose_next_agent
from agents.coordinator_agent.state import AgentState
from agents.coordinator_agent.synthesizer import synthesize_final_answer
from agents.coordinator_agent.tracing import TraceCollector
from agents.decision_agent.run import run_decision_state
from agents.nlp_agent.run import ReviewInsightAgent


def _load_sql_run_pipeline():
    sql_dir = Path(__file__).resolve().parents[1] / "sql_agent"
    run_path = sql_dir / "run.py"
    if str(sql_dir) not in sys.path:
        sys.path.insert(0, str(sql_dir))
    spec = importlib.util.spec_from_file_location("agentic_bi_sql_agent_run", run_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 SQL Agent：{run_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_sql_pipeline_with_feedback


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
    use_llm: bool = True,
    model=None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
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
    result = decompose_query(user_query, use_llm=use_llm, model=model)
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
    patch = decompose_to_state_patch(user_query, result)
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
    return {**state, **patch}


def orchestrator_node(
    state: AgentState,
    *,
    use_llm: bool = True,
    model=None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
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
    iterations = int(state.get("orchestrator_iterations") or 0) + 1
    decision = choose_next_agent(
        {**state, "orchestrator_iterations": iterations},
        use_llm=use_llm,
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
    log = _append_log(
        state,
        {
            "step": iterations,
            "next_agent": decision.next_agent,
            "reasoning": decision.reasoning,
        },
    )
    return {
        **state,
        "orchestrator_iterations": iterations,
        "next_agent": decision.next_agent,
        "execution_log": log,
    }


def data_analysis_node(
    state: AgentState,
    *,
    model=None,
    on_tool_end: Callable[[str, str], None] | None = None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    sub_questions = state.get("sub_questions") or [str(state.get("user_query") or "")]
    sql_runs = list(state.get("sql_runs") or [])
    idx = len(sql_runs)
    if idx >= len(sub_questions):
        return {**state, "agents_done": _mark_done(state, "data_analysis")}

    question = sub_questions[idx]
    run_sql = _load_sql_run_pipeline()
    sql_out = run_sql(question, model=model, on_tool_end=on_tool_end)
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
    sql_runs.append(
        {
            "question": question,
            "index": idx,
            "sql_pipeline": sql_out,
            "analysis_result": analysis,
            "execute_sql_json": sql_out.get("execute_sql_json", ""),
        }
    )
    merged = merge_sql_runs(sql_runs)
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
        next_state["warnings"] = _append_warning(
            next_state,
            f"子问题「{question}」SQL 未完全成功：{exec_payload.get('error_message') or '未知'}",
        )

    if len(sql_runs) >= len(sub_questions):
        next_state["agents_done"] = _mark_done(next_state, "data_analysis")
    return next_state


def visualization_node(
    state: AgentState,
    *,
    model=None,
    use_llm: bool = True,
    on_tool_end: Callable[[str, str], None] | None = None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
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
        return {
            **state,
            "agents_done": _mark_done(state, "visualization"),
            "visualization_result": {
                "skipped": True,
                "summary_text": "尚无 SQL 分析结果，跳过可视化。",
                "charts": [],
            },
        }

    viz_result = run_intelligent_visualization(
        user_query=str(state.get("user_query") or ""),
        intent=str(state.get("intent") or "descriptive"),
        sql_runs=sql_runs,
        review_insights=state.get("review_insights") or state.get("nlp_result"),
        model=model,
        use_llm=use_llm,
        on_tool_end=on_tool_end,
    )

    patch: dict[str, Any] = {}
    if viz_result.get("forecast_result") and not state.get("forecast_result"):
        patch["forecast_result"] = viz_result["forecast_result"]
    if not state.get("forecast_result") and not patch.get("forecast_result"):
        from agents.decision_agent.forecast_from_analysis import enrich_forecast_from_state

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

    return {
        **state,
        **patch,
        "visualization_result": viz_result,
        "agents_done": _mark_done(state, "visualization"),
    }


def nlp_node(
    state: AgentState,
    *,
    on_tool_end: Callable[[str, str], None] | None = None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    agent = ReviewInsightAgent()
    out = agent.run(dict(state), on_tool_end=on_tool_end)
    out["agents_done"] = _mark_done(out, "nlp")
    insights = out.get("review_insights") or {}
    _emit_trace(
        trace_collector,
        agent="nlp_agent",
        step="review_insights",
        kind="agent_result",
        title="评论洞察 Agent 完成",
        summary=str(insights.get("summary") or insights.get("summary_text") or "已完成评论主题、情感与词云数据整理。"),
    )
    return dict(out)


def decision_node(
    state: AgentState,
    *,
    model=None,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    out = run_decision_state(state, model=model)
    out["agents_done"] = _mark_done(out, "decision")
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
    return out


def synthesize_node(
    state: AgentState,
    *,
    model=None,
    use_llm: bool = True,
    trace_collector: TraceCollector | None = None,
) -> AgentState:
    if state.get("off_topic") and state.get("final_answer"):
        _emit_trace(
            trace_collector,
            agent="coordinator_agent",
            step="synthesize_answer",
            kind="final_answer",
            title="最终回答完成",
            summary=str(state.get("final_answer") or ""),
        )
        return {**state, "agents_done": _mark_done(state, "synthesize")}
    answer = synthesize_final_answer(state, model=model, use_llm=use_llm)
    _emit_trace(
        trace_collector,
        agent="coordinator_agent",
        step="synthesize_answer",
        kind="final_answer",
        title="最终回答完成",
        summary=answer,
    )
    return {**state, "final_answer": answer, "agents_done": _mark_done(state, "synthesize")}


def route_from_state(state: AgentState) -> str:
    nxt = str(state.get("next_agent") or "synthesize")
    allowed = {"data_analysis", "visualization", "nlp", "decision", "synthesize"}
    return nxt if nxt in allowed else "synthesize"
