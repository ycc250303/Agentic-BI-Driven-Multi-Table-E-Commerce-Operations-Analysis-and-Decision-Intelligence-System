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


def decompose_node(state: AgentState, *, use_llm: bool = True, model=None) -> AgentState:
    user_query = str(state.get("user_query") or state.get("question") or "").strip()
    if not user_query:
        return {
            **state,
            "warnings": _append_warning(state, "缺少 user_query，无法分解问题。"),
            "next_agent": "synthesize",
        }
    if is_off_topic_query(user_query):
        return {**state, **off_topic_state_patch(user_query)}
    result = decompose_query(user_query, use_llm=use_llm, model=model)
    if result.off_topic:
        return {**state, **off_topic_state_patch(user_query)}
    patch = decompose_to_state_patch(user_query, result)
    return {**state, **patch}


def orchestrator_node(state: AgentState, *, use_llm: bool = True, model=None) -> AgentState:
    if state.get("off_topic"):
        iterations = int(state.get("orchestrator_iterations") or 0) + 1
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
) -> AgentState:
    from agents.viz_agent.intelligent_viz import run_intelligent_visualization

    sql_runs = state.get("sql_runs") or []
    if not sql_runs:
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

    return {
        **state,
        **patch,
        "visualization_result": viz_result,
        "agents_done": _mark_done(state, "visualization"),
    }


def nlp_node(state: AgentState) -> AgentState:
    agent = ReviewInsightAgent()
    out = agent.run(dict(state))
    out["agents_done"] = _mark_done(out, "nlp")
    return dict(out)


def decision_node(state: AgentState, *, model=None) -> AgentState:
    out = run_decision_state(state, model=model)
    out["agents_done"] = _mark_done(out, "decision")
    return out


def synthesize_node(
    state: AgentState,
    *,
    model=None,
    use_llm: bool = True,
) -> AgentState:
    if state.get("off_topic") and state.get("final_answer"):
        return {**state, "agents_done": _mark_done(state, "synthesize")}
    answer = synthesize_final_answer(state, model=model, use_llm=use_llm)
    return {**state, "final_answer": answer, "agents_done": _mark_done(state, "synthesize")}


def route_from_state(state: AgentState) -> str:
    nxt = str(state.get("next_agent") or "synthesize")
    allowed = {"data_analysis", "visualization", "nlp", "decision", "synthesize"}
    return nxt if nxt in allowed else "synthesize"
