from __future__ import annotations

import json

import pytest

from agents.coordinator_agent.conversation_resolver import resolve_conversation_context
from agents.coordinator_agent.memory import (
    build_conversation_history,
    build_state_summary,
    update_memory_summary,
)
from agents.coordinator_agent.session_manager import CoordinatorRunOptions, SessionManager
from agents.coordinator_agent.session_store import LocalSessionStore
from agents.coordinator_agent.tracing import TraceCollector, summarize_tool_payload


class _FakeStructuredModel:
    def __init__(self, output):
        self.output = output

    def invoke(self, messages):
        return self.output


class _FakeModel:
    def __init__(self, output):
        self.output = output

    def with_structured_output(self, schema):
        if isinstance(self.output, dict) and schema.__name__ in self.output:
            return _FakeStructuredModel(self.output[schema.__name__])
        return _FakeStructuredModel(self.output)


class _FailingStructuredModel:
    def invoke(self, messages):
        raise RuntimeError("semantic resolver failed")


class _FailingModel:
    def with_structured_output(self, schema):
        return _FailingStructuredModel()


def test_local_session_store_roundtrip(tmp_path):
    store = LocalSessionStore(tmp_path)
    session = store.create_session(title="demo")
    session["turns"].append({"turn_id": 1, "user_query": "q", "final_answer": "a"})

    path = store.save_session(session)
    loaded = store.load_session(session["session_id"])

    assert path.is_file()
    assert loaded["session_id"] == session["session_id"]
    assert loaded["turns"][0]["final_answer"] == "a"
    assert store.list_sessions()[0]["turn_count"] == 1


def test_local_session_store_delete_session(tmp_path):
    store = LocalSessionStore(tmp_path)
    session = store.create_session(title="demo")
    store.save_session(session)
    sid = session["session_id"]

    store.delete_session(sid)

    assert not store._path(sid).is_file()
    assert store.list_sessions() == []
    with pytest.raises(FileNotFoundError):
        store.load_session(sid)


def test_session_manager_delete_session(tmp_path):
    manager = SessionManager(LocalSessionStore(tmp_path))
    session = manager.create_session(title="demo")
    sid = session["session_id"]

    manager.delete_session(sid)

    assert manager.list_sessions() == []


def test_first_turn_replaces_placeholder_title(tmp_path):
    manager = SessionManager(LocalSessionStore(tmp_path))
    session = manager.create_session(title="新对话")
    sid = session["session_id"]
    options = CoordinatorRunOptions(
        use_llm_plan=False,
        use_llm_viz=False,
        use_llm_synthesize=False,
    )
    model = _FakeModel(
        {
            "SessionMemorySummary": {
                "memory_summary": "用户询问 2017 GMV。",
                "updated_focus": "GMV",
            }
        }
    )

    manager.run_turn(
        query="2017 年 GMV 是多少？",
        session_id=sid,
        options=options,
        model=model,
    )

    loaded = manager.load_session(sid)
    assert loaded["title"] == "2017 年 GMV 是多少？"


def test_first_turn_keeps_custom_title(tmp_path):
    manager = SessionManager(LocalSessionStore(tmp_path))
    session = manager.create_session(title="我的分析专题")
    sid = session["session_id"]
    options = CoordinatorRunOptions(
        use_llm_plan=False,
        use_llm_viz=False,
        use_llm_synthesize=False,
    )
    model = _FakeModel(
        {
            "SessionMemorySummary": {
                "memory_summary": "摘要",
                "updated_focus": "focus",
            }
        }
    )

    manager.run_turn(
        query="2017 年 GMV 是多少？",
        session_id=sid,
        options=options,
        model=model,
    )

    loaded = manager.load_session(sid)
    assert loaded["title"] == "我的分析专题"


def test_resolve_conversation_context_first_turn_is_new_topic():
    result = resolve_conversation_context("分析 casa_conforto 品类的销售表现。", {"turns": []})

    assert result["relation_to_previous"] == "new_topic"
    assert result["resolved_task"] == "分析 casa_conforto 品类的销售表现。"
    assert result["confidence"] == 1.0


def test_resolve_conversation_context_uses_semantic_model_output():
    session = {
        "memory_summary": "用户正在评估 casa_conforto 品类是否适合入行，重点关注风险和机会。",
        "turns": [
            {
                "user_query": "casa_conforto 品类适不适合入行？我主要关心风险和机会。",
                "resolved_task": "评估 casa_conforto 品类是否适合入行，重点分析风险和机会。",
                "final_answer": "该品类评分较高但规模偏小，机会在差异化服务，风险在需求稳定性和物流履约。",
            }
        ]
    }
    model = _FakeModel(
        {
            "relation_to_previous": "scope_refinement",
            "resolved_task": "在上一轮风险与机会判断框架下，聚焦 SP 州评估 casa_conforto 品类入行风险更高还是更低、机会在哪里，并给出数据依据。",
            "context_used": "上一轮围绕 casa_conforto 品类入行前景，重点关注风险和机会。",
            "carried_over_goal": "判断入行风险与机会",
            "carried_over_subject": "casa_conforto 品类",
            "new_constraints": ["SP 州"],
            "changed_constraints": [],
            "needs_clarification": False,
            "clarification_question": "",
            "confidence": 0.93,
        }
    )

    result = resolve_conversation_context("那 SP 州呢？", session, model=model)

    assert result["relation_to_previous"] == "scope_refinement"
    assert "SP 州" in result["resolved_task"]
    assert "风险" in result["resolved_task"]
    assert "机会" in result["resolved_task"]
    assert result["carried_over_goal"] == "判断入行风险与机会"
    assert result["carried_over_subject"] == "casa_conforto 品类"


def test_resolve_conversation_context_does_not_fallback_on_model_error():
    session = {
        "memory_summary": "用户正在分析 casa_conforto 品类。",
        "turns": [
            {
                "turn_id": 1,
                "user_query": "分析 casa_conforto 的口碑。",
                "resolved_task": "分析 casa_conforto 品类的评论口碑。",
                "final_answer": "口碑整体偏正向。",
            }
        ],
    }

    with pytest.raises(RuntimeError):
        resolve_conversation_context("那 SP 州呢？", session, model=_FailingModel())


def test_build_conversation_history_uses_summary_and_recent_turns():
    session = {
        "memory_summary": "用户关注 casa_conforto。",
        "turns": [
            {"user_query": "q1", "final_answer": "a1"},
            {"user_query": "q2", "final_answer": "a2"},
        ],
    }

    history = build_conversation_history(session, recent_turns=1)

    assert history[0]["role"] == "system"
    assert history[1]["content"] == "q2"
    assert history[2]["content"] == "a2"


def test_update_memory_summary_llm_uses_model_output():
    session = {
        "memory_summary": "旧摘要",
        "turns": [
            {
                "turn_id": 1,
                "user_query": "分析 casa_conforto。",
                "resolved_task": "分析 casa_conforto 品类销售与口碑。",
                "final_answer": "销售规模较小但评分较高。",
                "state_summary": {"intent": "prescriptive"},
            }
        ],
    }
    model = _FakeModel(
        {
            "memory_summary": "用户关注 casa_conforto 品类的销售、口碑与进入前景；已知销售规模较小但评分较高。",
            "updated_focus": "casa_conforto 入行前景",
        }
    )

    summary = update_memory_summary(session, model=model)

    assert "casa_conforto" in summary
    assert "进入前景" in summary


def test_build_state_summary_keeps_high_signal_fields():
    summary = build_state_summary(
        {
            "intent": "descriptive",
            "sub_questions": ["q"],
            "suggested_agents": ["data_analysis"],
            "sql_runs": [{"question": "q"}],
            "visualization_result": {"charts": [{"ok": True}]},
        }
    )

    assert summary["intent"] == "descriptive"
    assert summary["sql_run_count"] == 1
    assert summary["chart_count"] == 1


def test_trace_collector_records_tool_summary():
    payload = json.dumps(
        {"ok": True, "results": [{"row_count_returned": 3}, {"row_count_returned": 2}]},
        ensure_ascii=False,
    )
    collector = TraceCollector(session_id="s1", turn_id=2)

    event = collector.emit_tool_result("execute_sql_tool", payload)

    assert event["event_id"] == "turn-2-001"
    assert event["agent"] == "data_analysis_agent"
    assert "返回 5 行" in event["summary"]
    assert collector.events[0]["payload_preview"]


def test_trace_collector_invokes_event_callback():
    seen = []
    collector = TraceCollector(session_id="s1", turn_id=1, on_event=seen.append)

    collector.emit(
        agent="coordinator_agent",
        step="decompose",
        kind="planning",
        title="完成",
        summary="问题分解完成。",
    )

    assert len(seen) == 1
    assert seen[0]["step"] == "decompose"


def test_trace_collector_carries_sqls_from_generate_to_execute():
    generate_payload = json.dumps(
        {
            "query_sqls": [
                "SELECT `customer_state`, SUM(`total_gmv`) AS `gmv` FROM `mv_state_sales` GROUP BY `customer_state`"
            ],
            "result_explanation": "按州统计 GMV。",
        },
        ensure_ascii=False,
    )
    execute_payload = json.dumps(
        {"ok": True, "results": [{"index": 0, "ok": True, "row_count_returned": 27}]},
        ensure_ascii=False,
    )
    collector = TraceCollector(session_id="s1", turn_id=1)

    generate_event = collector.emit_tool_result("generate_sql_tool", generate_payload)
    execute_event = collector.emit_tool_result("execute_sql_tool", execute_payload)

    assert generate_event["metadata"]["sqls"][0].startswith("SELECT")
    assert execute_event["metadata"]["sqls"] == generate_event["metadata"]["sqls"]


def test_summarize_tool_payload_handles_generate_sql():
    payload = json.dumps(
        {"query_sqls": ["select 1", "select 2"], "result_explanation": "用于对比两项指标。"},
        ensure_ascii=False,
    )

    summary = summarize_tool_payload("generate_sql_tool", payload)

    assert "生成 2 条 SQL" in summary
    assert "对比两项指标" in summary


def test_session_manager_stream_turn_events_emits_realtime_shape(tmp_path):
    manager = SessionManager(LocalSessionStore(tmp_path))
    options = CoordinatorRunOptions(
        use_llm_plan=False,
        use_llm_viz=False,
        use_llm_synthesize=False,
    )
    model = _FakeModel(
        {
            "SessionMemorySummary": {
                "memory_summary": "用户刚开始一轮问答。",
                "updated_focus": "初始问题",
            }
        }
    )

    events = list(
        manager.stream_turn_events(
            query="你好",
            new_session=True,
            options=options,
            model=model,
        )
    )

    types = [event["type"] for event in events]
    assert types[0] == "turn.started"
    assert "trace.event" in types
    assert types[-2] == "answer.final"
    assert types[-1] == "turn.completed"
    assert events[0]["data"]["user_query"] == "你好"
    assert events[0]["data"]["resolved_task"] == "你好"
