"""全项目唯一 DeepSeek / Chat 入口。

自由文本用 ``get_llm`` / ``invoke_chat``（可跟随思考开关）；
结构化 JSON 用 ``get_structured_llm`` / ``invoke_structured``（始终关思考）。
超时与有限重试走 ChatDeepSeek 客户端参数，不在此再套 schema 重试循环。
"""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from pydantic import ValidationError

from agents.common.logging import get_session_id

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 60.0
DEFAULT_MAX_RETRIES = 2

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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def llm_timeout_sec() -> float:
    return _env_float("AGENTIC_BI_LLM_TIMEOUT", DEFAULT_TIMEOUT_SEC)


def llm_max_retries() -> int:
    return _env_int("AGENTIC_BI_LLM_MAX_RETRIES", DEFAULT_MAX_RETRIES)


def llm_error_kind(exc: BaseException) -> str:
    """区分缺 Key / 429 / 超时 / schema 失败，便于日志与 warnings。不建异常基类。"""
    name = type(exc).__name__
    message = str(exc)
    if isinstance(exc, RuntimeError) and "DEEPSEEK_API_KEY" in message:
        return "missing_api_key"
    if isinstance(exc, ValidationError) or name == "ValidationError":
        return "schema_failure"
    if "RateLimit" in name or "429" in message:
        return "rate_limit"
    if "Timeout" in name or "timed out" in message.lower():
        return "timeout"
    return "llm_error"


def _invoke_config() -> dict[str, Any] | None:
    session_id = get_session_id()
    if not session_id or session_id == "-":
        return None
    return {"metadata": {"session_id": session_id}}


def _call_invoke(runnable: Any, messages: Any) -> Any:
    config = _invoke_config()
    if not config:
        return runnable.invoke(messages)
    try:
        return runnable.invoke(messages, config=config)
    except TypeError:
        return runnable.invoke(messages)


@lru_cache(maxsize=8)
def _get_llm_cached(thinking_enabled: bool, timeout: float, max_retries: int) -> ChatDeepSeek:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "缺少环境变量 DEEPSEEK_API_KEY。请在 .env 或系统环境变量中配置后再运行。"
        )
    kwargs: dict = {
        "model": "deepseek-v4-flash",
        "timeout": timeout,
        "max_retries": max_retries,
        "extra_body": _thinking_extra_body(thinking_enabled=thinking_enabled),
    }
    if thinking_enabled:
        kwargs["reasoning_effort"] = "high"
    return ChatDeepSeek(**kwargs)


def get_llm() -> ChatDeepSeek:
    """自由文本调用（分解/路由/汇总等）；可随 Dashboard 开关启用思考模式。"""
    return _get_llm_cached(
        is_deepseek_thinking_enabled(),
        llm_timeout_sec(),
        llm_max_retries(),
    )


def get_structured_llm() -> ChatDeepSeek:
    """结构化 JSON 输出（rewrite/generate_sql/记忆等）。

    DeepSeek 思考模式与 LangChain ``with_structured_output`` 不兼容
    （API 返回 ``Thinking mode does not support this tool_choice``），
    因此结构化步骤始终关闭思考模式。
    """
    return _get_llm_cached(False, llm_timeout_sec(), llm_max_retries())


def invoke_chat(messages: Any, *, model: Any | None = None) -> str:
    """调用自由文本模型一次，返回 ``content`` 字符串。

    ``model`` 非空时用注入模型（测试），否则 ``get_llm()``。
    """
    llm = model if model is not None else get_llm()
    started = time.perf_counter()
    try:
        resp = _call_invoke(llm, messages)
        content = getattr(resp, "content", resp)
        logger.info(
            "event=llm_call kind=ok structured=0 elapsed_ms=%.0f",
            (time.perf_counter() - started) * 1000,
        )
        return str(content)
    except Exception as exc:
        logger.warning(
            "event=llm_call kind=%s structured=0 elapsed_ms=%.0f err=%s",
            llm_error_kind(exc),
            (time.perf_counter() - started) * 1000,
            exc,
        )
        raise


def invoke_structured(schema: Any, messages: Any, *, model: Any | None = None) -> Any:
    """用 ``with_structured_output(schema)`` 调用一次并返回结构化结果。

    ``model`` 非空时用注入模型，否则 ``get_structured_llm()``。
    """
    llm = model if model is not None else get_structured_llm()
    started = time.perf_counter()
    try:
        result = _call_invoke(llm.with_structured_output(schema), messages)
        logger.info(
            "event=llm_call kind=ok structured=1 elapsed_ms=%.0f",
            (time.perf_counter() - started) * 1000,
        )
        return result
    except Exception as exc:
        logger.warning(
            "event=llm_call kind=%s structured=1 elapsed_ms=%.0f err=%s",
            llm_error_kind(exc),
            (time.perf_counter() - started) * 1000,
            exc,
        )
        raise
