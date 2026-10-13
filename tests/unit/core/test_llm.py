from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, SecretStr

import agentic_bi.core.llm as llm_module
from agentic_bi.core.llm import ModelGateway
from agentic_bi.core.settings import ModelProvider, Settings


class Answer(BaseModel):
    value: str


class FakeStructuredRunnable:
    def invoke(self, messages: Any, config: Any = None) -> Answer:
        return Answer(value="structured")


class FakeChatModel:
    def __init__(self) -> None:
        self.structured_method: str | None = None

    def invoke(self, messages: Any, config: Any = None) -> AIMessage:
        return AIMessage(content="plain")

    def with_structured_output(
        self,
        schema: type[BaseModel],
        *,
        method: str,
    ) -> FakeStructuredRunnable:
        self.structured_method = method
        return FakeStructuredRunnable()


def test_deepseek_and_qwen_use_one_gateway(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_constructor(**kwargs: Any) -> FakeChatModel:
        calls.append(kwargs)
        return FakeChatModel()

    monkeypatch.setattr(llm_module, "ChatDeepSeek", fake_constructor)
    monkeypatch.setattr(llm_module, "ChatOpenAI", fake_constructor)
    settings = Settings(
        _env_file=None,
        deepseek_api_key=SecretStr("deepseek-key"),
        dashscope_api_key=SecretStr("qwen-key"),
    )
    gateway = ModelGateway(settings)

    plain = gateway.invoke([HumanMessage(content="hello")])
    structured = gateway.invoke_structured(
        Answer,
        [HumanMessage(content="hello")],
        provider=ModelProvider.QWEN,
    )

    assert plain.content == "plain"
    assert structured == Answer(value="structured")
    assert calls[0]["model"] == "deepseek-v4-flash"
    assert calls[1]["model"] == "qwen3.8-max"
    assert "base_url" in calls[1]


def test_structured_deepseek_disables_thinking(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_constructor(**kwargs: Any) -> FakeChatModel:
        calls.append(kwargs)
        return FakeChatModel()

    monkeypatch.setattr(llm_module, "ChatDeepSeek", fake_constructor)
    settings = Settings(
        _env_file=None,
        llm_thinking_enabled=True,
        deepseek_api_key=SecretStr("deepseek-key"),
    )
    gateway = ModelGateway(settings)

    gateway.invoke_structured(Answer, [HumanMessage(content="hello")])

    assert calls[0]["extra_body"] is None
