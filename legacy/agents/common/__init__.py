"""跨 Agent 基础设施。调模型只经 ``agents.common.llm``；读 ``config/`` 经 ``agents.common.paths``；拼 LLM system 经 ``agents.common.prompts``。"""

from agents.common.llm import (
    get_llm,
    get_llm_provider,
    get_structured_llm,
    has_provider_api_key,
    invoke_chat,
    invoke_structured,
    is_deepseek_thinking_enabled,
    is_thinking_enabled,
    llm_error_kind,
    set_deepseek_thinking_enabled,
    set_llm_provider,
    set_thinking_enabled,
)

__all__ = [
    "get_llm",
    "get_llm_provider",
    "get_structured_llm",
    "has_provider_api_key",
    "invoke_chat",
    "invoke_structured",
    "is_deepseek_thinking_enabled",
    "is_thinking_enabled",
    "llm_error_kind",
    "set_deepseek_thinking_enabled",
    "set_llm_provider",
    "set_thinking_enabled",
]
