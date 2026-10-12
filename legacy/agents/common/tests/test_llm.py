from __future__ import annotations

import os

import pytest

from agents.common import llm as llm_mod
from agents.common.llm import (
    get_llm,
    get_llm_provider,
    get_structured_llm,
    invoke_chat,
    invoke_structured,
    is_deepseek_thinking_enabled,
    is_thinking_enabled,
    llm_error_kind,
    set_deepseek_thinking_enabled,
    set_llm_provider,
    set_thinking_enabled,
)

_HAS_LIVE_KEY = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
_HAS_QWEN_KEY = bool(os.getenv("DASHSCOPE_API_KEY", "").strip())


@pytest.fixture(autouse=True)
def reset_llm_runtime():
    llm_mod._get_llm_cached.cache_clear()
    llm_mod._runtime_provider = None
    llm_mod._runtime_thinking_enabled = None
    yield
    llm_mod._get_llm_cached.cache_clear()
    llm_mod._runtime_provider = None
    llm_mod._runtime_thinking_enabled = None


@pytest.fixture
def dummy_api_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY") or "test-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", os.getenv("DASHSCOPE_API_KEY") or "test-key")
    llm_mod._get_llm_cached.cache_clear()
    yield
    llm_mod._get_llm_cached.cache_clear()


def test_get_llm_respects_thinking_toggle(dummy_api_key):
    set_deepseek_thinking_enabled(False)
    llm_off = get_llm()
    assert llm_off.extra_body == {"thinking": {"type": "disabled"}}

    set_deepseek_thinking_enabled(True)
    llm_on = get_llm()
    assert llm_on.extra_body == {"thinking": {"type": "enabled"}}
    assert llm_on is not llm_off
    assert is_deepseek_thinking_enabled() is True
    assert is_thinking_enabled() is True

    set_deepseek_thinking_enabled(False)


def test_structured_llm_always_disables_thinking(dummy_api_key):
    set_deepseek_thinking_enabled(True)
    structured = get_structured_llm()
    assert structured.extra_body == {"thinking": {"type": "disabled"}}
    set_deepseek_thinking_enabled(False)


def test_qwen_thinking_extra_body(dummy_api_key):
    set_llm_provider("qwen")
    set_thinking_enabled(False)
    llm_off = get_llm()
    assert llm_off.extra_body == {"enable_thinking": False}
    assert getattr(llm_off, "model_name", "") == "qwen3.8-max"

    set_thinking_enabled(True)
    llm_on = get_llm()
    assert llm_on.extra_body == {"enable_thinking": True}
    assert llm_on is not llm_off
    assert getattr(llm_on, "use_responses_api", False) is False


def test_qwen_structured_llm_always_disables_thinking(dummy_api_key):
    set_llm_provider("qwen")
    set_thinking_enabled(True)
    structured = get_structured_llm()
    assert structured.extra_body == {"enable_thinking": False}


def test_provider_switch_uses_separate_cache(dummy_api_key):
    set_llm_provider("deepseek")
    deepseek = get_llm()
    set_llm_provider("qwen")
    qwen = get_llm()
    assert deepseek is not qwen
    assert get_llm_provider() == "qwen"


def test_missing_dashscope_key_raises(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    set_llm_provider("qwen")
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        get_llm()


@pytest.mark.live
@pytest.mark.skipif(not _HAS_LIVE_KEY, reason="needs DEEPSEEK_API_KEY")
def test_thinking_mode_rejects_structured_output():
    from pydantic import BaseModel, Field

    class Out(BaseModel):
        answer: str = Field(description="short answer")

    set_deepseek_thinking_enabled(True)
    with pytest.raises(Exception) as exc:
        get_llm().with_structured_output(Out).invoke("Say hello")
    assert "400" in str(exc.value) or "tool_choice" in str(exc.value).lower()

    set_deepseek_thinking_enabled(False)


@pytest.mark.live
@pytest.mark.skipif(not _HAS_QWEN_KEY, reason="needs DASHSCOPE_API_KEY")
def test_qwen_structured_output_with_thinking_disabled():
    from pydantic import BaseModel, Field

    class Out(BaseModel):
        answer: str = Field(description="short answer")

    set_llm_provider("qwen")
    set_thinking_enabled(True)
    result = invoke_structured(Out, "Reply with answer hello")
    answer = result.answer if hasattr(result, "answer") else result["answer"]
    assert str(answer).strip()


def test_invoke_chat_uses_injected_model():
    class _Resp:
        content = "hello"

    class _Fake:
        def invoke(self, messages, config=None):
            assert messages == ["x"]
            return _Resp()

    assert invoke_chat(["x"], model=_Fake()) == "hello"


def test_invoke_chat_extracts_text_blocks_not_reasoning():
    class _Resp:
        content = [{"type": "text", "text": "final"}]
        additional_kwargs = {"reasoning_content": "secret thinking"}

    class _Fake:
        def invoke(self, messages, config=None):
            return _Resp()

    assert invoke_chat(["x"], model=_Fake()) == "final"


def test_invoke_chat_passes_session_id_metadata():
    seen: dict = {}

    class _Resp:
        content = "ok"

    class _Fake:
        def invoke(self, messages, config=None):
            seen["config"] = config
            return _Resp()

    from agents.common.logging import bind_session_id

    with bind_session_id("sess-9"):
        assert invoke_chat(["x"], model=_Fake()) == "ok"
    assert seen["config"]["metadata"]["session_id"] == "sess-9"


def test_invoke_structured_uses_injected_model():
    class Out:
        pass

    class _Fake:
        def with_structured_output(self, schema):
            assert schema is Out
            return self

        def invoke(self, messages, config=None):
            assert messages == ["y"]
            return {"ok": True}

    assert invoke_structured(Out, ["y"], model=_Fake()) == {"ok": True}


def test_invoke_structured_qwen_uses_json_schema(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    set_llm_provider("qwen")
    seen: dict = {}

    class _Fake:
        def with_structured_output(self, schema, **kwargs):
            seen["kwargs"] = kwargs
            return self

        def invoke(self, messages, config=None):
            return {"ok": True}

    monkeypatch.setattr(llm_mod, "get_structured_llm", lambda: _Fake())
    assert invoke_structured(object, ["y"]) == {"ok": True}
    assert seen["kwargs"].get("method") == "json_schema"


def test_invoke_structured_deepseek_keeps_default_method(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    set_llm_provider("deepseek")
    seen: dict = {}

    class _Fake:
        def with_structured_output(self, schema, **kwargs):
            seen["kwargs"] = kwargs
            return self

        def invoke(self, messages, config=None):
            return {"ok": True}

    monkeypatch.setattr(llm_mod, "get_structured_llm", lambda: _Fake())
    assert invoke_structured(object, ["y"]) == {"ok": True}
    assert "method" not in seen["kwargs"]


def test_llm_error_kind_classifies_missing_key_rate_limit_schema_timeout():
    from pydantic import BaseModel, ValidationError

    assert llm_error_kind(RuntimeError("缺少环境变量 DEEPSEEK_API_KEY。")) == "missing_api_key"
    assert llm_error_kind(RuntimeError("缺少环境变量 DASHSCOPE_API_KEY。")) == "missing_api_key"

    class RateLimitError(Exception):
        pass

    assert llm_error_kind(RateLimitError("Error code: 429")) == "rate_limit"

    class APITimeoutError(Exception):
        pass

    assert llm_error_kind(APITimeoutError("request timed out")) == "timeout"

    class Out(BaseModel):
        n: int

    try:
        Out.model_validate({"n": "x"})
    except ValidationError as exc:
        assert llm_error_kind(exc) == "schema_failure"


def test_invoke_chat_logs_and_reraises_classified_error(caplog):
    class _Fake:
        def invoke(self, messages, config=None):
            raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY。")

    with caplog.at_level("WARNING"):
        with pytest.raises(RuntimeError):
            invoke_chat(["x"], model=_Fake())
    assert "missing_api_key" in caplog.text


def test_get_llm_uses_timeout_and_retries(dummy_api_key, monkeypatch):
    monkeypatch.setenv("AGENTIC_BI_LLM_TIMEOUT", "12")
    monkeypatch.setenv("AGENTIC_BI_LLM_MAX_RETRIES", "3")
    llm_mod._get_llm_cached.cache_clear()
    llm = get_llm()
    timeout = getattr(llm, "request_timeout", None)
    assert timeout == 12 or timeout == 12.0
    assert llm.max_retries == 3
