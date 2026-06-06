from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph

from agents.coordinator_agent.nodes import (
    data_analysis_node,
    decompose_node,
    decision_node,
    nlp_node,
    orchestrator_node,
    route_from_state,
    synthesize_node,
    visualization_node,
)
from agents.coordinator_agent.state import AgentState
from agents.coordinator_agent.tracing import TraceCollector


def build_coordinator_graph(
    *,
    model=None,
    use_llm_plan: bool = True,
    use_llm_viz: bool = True,
    use_llm_synthesize: bool = True,
    on_tool_end: Callable[[str, str], None] | None = None,
    trace_collector: TraceCollector | None = None,
):
    """迭代式 LangGraph：decompose → orchestrator ⇄ agents → synthesize。"""

    def _tool_end(tool: str, payload: str) -> None:
        if trace_collector is not None:
            trace_collector.emit_tool_result(tool, payload)
        if on_tool_end is not None:
            on_tool_end(tool, payload)

    def _decompose(s: AgentState) -> AgentState:
        return decompose_node(
            s,
            use_llm=use_llm_plan,
            model=model,
            trace_collector=trace_collector,
        )

    def _orchestrator(s: AgentState) -> AgentState:
        return orchestrator_node(
            s,
            use_llm=use_llm_plan,
            model=model,
            trace_collector=trace_collector,
        )

    def _sql(s: AgentState) -> AgentState:
        return data_analysis_node(
            s,
            model=model,
            on_tool_end=_tool_end,
            trace_collector=trace_collector,
        )

    def _viz(s: AgentState) -> AgentState:
        return visualization_node(
            s,
            model=model,
            use_llm=use_llm_viz,
            on_tool_end=_tool_end,
            trace_collector=trace_collector,
        )

    def _nlp(s: AgentState) -> AgentState:
        return nlp_node(s, on_tool_end=_tool_end, trace_collector=trace_collector)

    def _decision(s: AgentState) -> AgentState:
        return decision_node(s, model=model, trace_collector=trace_collector)

    def _synthesize(s: AgentState) -> AgentState:
        return synthesize_node(
            s,
            model=model,
            use_llm=use_llm_synthesize,
            trace_collector=trace_collector,
        )

    workflow = StateGraph(AgentState)
    workflow.add_node("decompose", _decompose)
    workflow.add_node("orchestrator", _orchestrator)
    workflow.add_node("data_analysis", _sql)
    workflow.add_node("visualization", _viz)
    workflow.add_node("nlp", _nlp)
    workflow.add_node("decision", _decision)
    workflow.add_node("synthesize", _synthesize)

    workflow.set_entry_point("decompose")
    workflow.add_edge("decompose", "orchestrator")

    workflow.add_conditional_edges(
        "orchestrator",
        route_from_state,
        {
            "data_analysis": "data_analysis",
            "visualization": "visualization",
            "nlp": "nlp",
            "decision": "decision",
            "synthesize": "synthesize",
        },
    )

    for node in ("data_analysis", "visualization", "nlp", "decision"):
        workflow.add_edge(node, "orchestrator")

    workflow.add_edge("synthesize", END)
    return workflow.compile()


def run_coordinator(
    user_query: str,
    *,
    model=None,
    use_llm_plan: bool = True,
    use_llm_viz: bool = True,
    use_llm_synthesize: bool = True,
    on_tool_end: Callable[[str, str], None] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    trace_collector: TraceCollector | None = None,
) -> dict[str, Any]:
    graph = build_coordinator_graph(
        model=model,
        use_llm_plan=use_llm_plan,
        use_llm_viz=use_llm_viz,
        use_llm_synthesize=use_llm_synthesize,
        on_tool_end=on_tool_end,
        trace_collector=trace_collector,
    )
    initial: AgentState = {
        "user_query": user_query,
        "question": user_query,
        "conversation_history": list(conversation_history or []),
    }
    return graph.invoke(initial)
