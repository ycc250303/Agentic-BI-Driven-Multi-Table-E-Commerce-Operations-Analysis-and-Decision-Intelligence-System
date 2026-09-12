"""决策 Agent 测试替身：拦截 common.llm 入口，不在决策层注入独立模型。"""

from __future__ import annotations

import importlib

import pytest

DEFAULT_NARRATIVE = {
    "narrative_answer": "根据证据，建议优先治理配送延迟与高负面区域。",
    "risks": ["测试模式下未接入真实 API"],
    "assumptions": ["使用 fixture 数据进行验证"],
}

DEFAULT_PLAN = {
    "has_what_if_intent": False,
    "question": "",
}

_SERVICE = importlib.import_module("agents.decision_agent.service")
_PLAN_WHAT_IF = importlib.import_module("agents.decision_agent.tools.plan_what_if")


def apply_decision_llm_stub(
    monkeypatch,
    *,
    plan=None,
    narrative=None,
    fail_plan: bool = False,
    empty_narrative: bool = False,
) -> None:
    plan_payload = DEFAULT_PLAN if plan is None else plan
    narrative_payload = DEFAULT_NARRATIVE if narrative is None else narrative

    def fake(schema, messages, **_kwargs):
        name = getattr(schema, "__name__", "")
        if name == "WhatIfPlan":
            if fail_plan:
                raise RuntimeError("planner unavailable")
            return plan_payload
        if empty_narrative:
            return None
        return narrative_payload

    monkeypatch.setattr(_SERVICE, "invoke_structured", fake)
    monkeypatch.setattr(_PLAN_WHAT_IF, "invoke_structured", fake)


@pytest.fixture
def stub_decision_llm(monkeypatch):
    def _apply(**kwargs):
        apply_decision_llm_stub(monkeypatch, **kwargs)

    return _apply
