"""全项目唯一 DeepSeek / Chat 入口。

自由文本用 ``get_llm`` / ``invoke_chat``（可跟随思考开关）；
结构化 JSON 用 ``get_structured_llm`` / ``invoke_structured``（始终关思考）。
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

_runtime_thinking_enabled: bool | None = None


def _env_thinking_default() -> bool | None:
    raw = os.getenv("DEEPSEEK_THINKING_ENABLED", "").strip().lower()
    if raw in ("1", "true", "yes", "on", "enabled"):
        return True
    if raw in ("0", "false", "no", "off", "disabled"):
        return False
    return None


def is_deepseek_thinking_enabled() -> bool:
    if _runtime_thinking_enabled is not None:
        return _runtime_thinking_enabled
    env_default = _env_thinking_default()
    if env_default is not None:
        return env_default
    return False


def set_deepseek_thinking_enabled(enabled: bool) -> None:
    global _runtime_thinking_enabled
    _runtime_thinking_enabled = bool(enabled)


def _thinking_extra_body(*, thinking_enabled: bool) -> dict:
    mode = "enabled" if thinking_enabled else "disabled"
    return {"thinking": {"type": mode}}


@lru_cache(maxsize=2)
def _get_llm_cached(thinking_enabled: bool) -> ChatDeepSeek:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "缺少环境变量 DEEPSEEK_API_KEY。请在 .env 或系统环境变量中配置后再运行。"
        )
    kwargs: dict = {
        "model": "deepseek-v4-flash",
        "extra_body": _thinking_extra_body(thinking_enabled=thinking_enabled),
    }
    if thinking_enabled:
        kwargs["reasoning_effort"] = "high"
    return ChatDeepSeek(**kwargs)


def get_llm() -> ChatDeepSeek:
    """自由文本调用（分解/路由/汇总等）；可随 Dashboard 开关启用思考模式。"""
    return _get_llm_cached(is_deepseek_thinking_enabled())


def get_structured_llm() -> ChatDeepSeek:
    """结构化 JSON 输出（rewrite/generate_sql/记忆等）。

    DeepSeek 思考模式与 LangChain ``with_structured_output`` 不兼容
    （API 返回 ``Thinking mode does not support this tool_choice``），
    因此结构化步骤始终关闭思考模式。
    """
    return _get_llm_cached(False)


def invoke_chat(messages: Any, *, model: Any | None = None) -> str:
    """调用自由文本模型一次，返回 ``content`` 字符串。

    ``model`` 非空时用注入模型（测试），否则 ``get_llm()``。
    """
    llm = model if model is not None else get_llm()
    resp = llm.invoke(messages)
    content = getattr(resp, "content", resp)
    return str(content)


def invoke_structured(schema: Any, messages: Any, *, model: Any | None = None) -> Any:
    """用 ``with_structured_output(schema)`` 调用一次并返回结构化结果。

    ``model`` 非空时用注入模型，否则 ``get_structured_llm()``。
    """
    llm = model if model is not None else get_structured_llm()
    return llm.with_structured_output(schema).invoke(messages)
