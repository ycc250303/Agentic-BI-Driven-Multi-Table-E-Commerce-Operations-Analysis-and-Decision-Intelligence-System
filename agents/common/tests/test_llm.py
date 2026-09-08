from __future__ import annotations

import pytest

from agents.common.llm import (
    get_llm,
    get_structured_llm,
    invoke_chat,
    invoke_structured,
    is_deepseek_thinking_enabled,
    set_deepseek_thinking_enabled,
)


def test_get_llm_respects_thinking_toggle():
    set_deepseek_thinking_enabled(False)
    llm_off = get_llm()
    assert llm_off.extra_body == {"thinking": {"type": "disabled"}}

    set_deepseek_thinking_enabled(True)
    llm_on = get_llm()
    assert llm_on.extra_body == {"thinking": {"type": "enabled"}}
    assert llm_on is not llm_off
    assert is_deepseek_thinking_enabled() is True

    set_deepseek_thinking_enabled(False)


def test_structured_llm_always_disables_thinking():
    set_deepseek_thinking_enabled(True)
    structured = get_structured_llm()
    assert structured.extra_body == {"thinking": {"type": "disabled"}}
    set_deepseek_thinking_enabled(False)


def test_thinking_mode_rejects_structured_output():
    from pydantic import BaseModel, Field

    class Out(BaseModel):
        answer: str = Field(description="short answer")

    set_deepseek_thinking_enabled(True)
    with pytest.raises(Exception) as exc:
        get_llm().with_structured_output(Out).invoke("Say hello")
    assert "400" in str(exc.value) or "tool_choice" in str(exc.value).lower()

    set_deepseek_thinking_enabled(False)


def test_invoke_chat_uses_injected_model():
    class _Resp:
        content = "hello"

    class _Fake:
        def invoke(self, messages):
            assert messages == ["x"]
            return _Resp()

    assert invoke_chat(["x"], model=_Fake()) == "hello"


def test_invoke_structured_uses_injected_model():
    class Out:
        pass

    class _Fake:
        def with_structured_output(self, schema):
            assert schema is Out
            return self

        def invoke(self, messages):
            assert messages == ["y"]
            return {"ok": True}

    assert invoke_structured(Out, ["y"], model=_Fake()) == {"ok": True}
