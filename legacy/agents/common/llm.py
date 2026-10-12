"""全项目唯一 Chat 入口（DeepSeek / 通义千问）。

自由文本用 ``get_llm`` / ``invoke_chat``（可跟随思考开关）；
结构化 JSON 用 ``get_structured_llm`` / ``invoke_structured``（始终关思考）。
超时与有限重试走客户端参数，不在此再套 schema 重试循环。
提供商差异只留在本模块；调用方不要自行构造 Chat 客户端。
"""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from typing import Any, Literal

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from agents.common.logging import get_session_id

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 60.0
DEFAULT_MAX_RETRIES = 2

LLMProvider = Literal["deepseek", "qwen"]
LLM_PROVIDERS: tuple[LLMProvider, ...] = ("deepseek", "qwen")
DEFAULT_PROVIDER: LLMProvider = "deepseek"
DEEPSEEK_MODEL = "deepseek-v4-flash"
QWEN_MODEL = "qwen3.8-max"
QWEN_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_PROVIDER_LABELS = {
    "deepseek": "DeepSeek（deepseek-v4-flash）",
    "qwen": "通义千问（qwen3.8-max）",
}

_runtime_thinking_enabled: bool | None = None
_runtime_provider: LLMProvider | None = None


def _load_env() -> None:
    load_dotenv()


def _parse_bool_env(raw: str) -> bool | None:
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on", "enabled"):
        return True
    if value in ("0", "false", "no", "off", "disabled"):
        return False
    return None


def _env_thinking_default() -> bool | None:
    for name in ("AGENTIC_BI_LLM_THINKING_ENABLED", "DEEPSEEK_THINKING_ENABLED"):
        parsed = _parse_bool_env(os.getenv(name, ""))
        if parsed is not None:
            return parsed
    return None


def _normalize_provider(raw: str) -> LLMProvider:
    value = raw.strip().lower()
    if value in ("qwen", "dashscope", "tongyi"):
        return "qwen"
    if value in ("deepseek", ""):
        return "deepseek"
    raise ValueError(f"未知 LLM 提供商：{raw!r}，可选 deepseek / qwen")


def get_llm_provider() -> LLMProvider:
    if _runtime_provider is not None:
        return _runtime_provider
    _load_env()
    raw = os.getenv("AGENTIC_BI_LLM_PROVIDER", "").strip()
    if not raw:
        return DEFAULT_PROVIDER
    try:
        return _normalize_provider(raw)
    except ValueError:
        logger.warning("event=llm_provider kind=invalid value=%s fallback=%s", raw, DEFAULT_PROVIDER)
        return DEFAULT_PROVIDER


def set_llm_provider(provider: str) -> None:
    """设置当前进程使用的 LLM 提供商（Dashboard / 测试）。"""
    global _runtime_provider
    _runtime_provider = _normalize_provider(provider)


def provider_api_key_env(provider: str | None = None) -> str:
    name = provider or get_llm_provider()
    return "DASHSCOPE_API_KEY" if name == "qwen" else "DEEPSEEK_API_KEY"


def has_provider_api_key(provider: str | None = None) -> bool:
    _load_env()
    return bool(os.getenv(provider_api_key_env(provider), "").strip())


def is_thinking_enabled() -> bool:
    if _runtime_thinking_enabled is not None:
        return _runtime_thinking_enabled
    env_default = _env_thinking_default()
    if env_default is not None:
        return env_default
    return False


def set_thinking_enabled(enabled: bool) -> None:
    """设置自由文本调用是否启用思考模式。"""
    global _runtime_thinking_enabled
    _runtime_thinking_enabled = bool(enabled)


def is_deepseek_thinking_enabled() -> bool:
    return is_thinking_enabled()


def set_deepseek_thinking_enabled(enabled: bool) -> None:
    set_thinking_enabled(enabled)


def _thinking_extra_body(provider: str, *, thinking_enabled: bool) -> dict:
    """按提供商组装思考开关。Qwen 必须显式 false，否则 qwen3.8-max 默认开思考。"""
    if provider == "qwen":
        return {"enable_thinking": bool(thinking_enabled)}
    mode = "enabled" if thinking_enabled else "disabled"
    return {"thinking": {"type": mode}}


def _qwen_base_url() -> str:
    _load_env()
    return os.getenv("DASHSCOPE_BASE_URL", "").strip() or QWEN_DEFAULT_BASE_URL


def _env_float(name: str, default: float) -> float:
    """获取环境变量并转换为浮点数，如果转换失败则返回默认值。"""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    """获取环境变量并转换为整数，如果转换失败则返回默认值。"""
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
    if isinstance(exc, RuntimeError) and (
        "DEEPSEEK_API_KEY" in message or "DASHSCOPE_API_KEY" in message
    ):
        return "missing_api_key"
    if isinstance(exc, ValidationError) or name == "ValidationError":
        return "schema_failure"
    if "RateLimit" in name or "429" in message:
        return "rate_limit"
    if "Timeout" in name or "timed out" in message.lower():
        return "timeout"
    return "llm_error"


def _invoke_config() -> dict[str, Any] | None:
    """组装请求 metadata，便于日志关联会话。"""
    session_id = get_session_id()
    if not session_id or session_id == "-":
        return None
    return {"metadata": {"session_id": session_id}}


def _call_invoke(runnable: Any, messages: Any) -> Any:
    """调用当前 Chat 模型，返回响应结果。"""
    config = _invoke_config()
    if not config:
        return runnable.invoke(messages)
    try:
        return runnable.invoke(messages, config=config)
    except TypeError:
        return runnable.invoke(messages)


def _extract_chat_text(resp: Any) -> str:
    """抽取最终作答文本，不把 reasoning_content 拼进回答。"""
    content = getattr(resp, "content", resp)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if isinstance(block, dict):
                block_type = str(block.get("type") or "text")
                if block_type in ("text", "output_text"):
                    text = block.get("text") or block.get("content") or ""
                    if text:
                        parts.append(str(text))
                continue
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        return "".join(parts)
    return str(content)


def _require_api_key(env_name: str) -> str:
    _load_env()
    api_key = os.getenv(env_name, "").strip()
    if not api_key:
        raise RuntimeError(
            f"缺少环境变量 {env_name}。请在 .env 或系统环境变量中配置后再运行。"
        )
    return api_key


def _build_deepseek_llm(*, thinking_enabled: bool, timeout: float, max_retries: int) -> ChatDeepSeek:
    api_key = _require_api_key("DEEPSEEK_API_KEY")
    kwargs: dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "api_key": api_key,
        "timeout": timeout,
        "max_retries": max_retries,
        "extra_body": _thinking_extra_body("deepseek", thinking_enabled=thinking_enabled),
    }
    if thinking_enabled:
        kwargs["reasoning_effort"] = "high"
    return ChatDeepSeek(**kwargs)


def _build_qwen_llm(
    *,
    thinking_enabled: bool,
    timeout: float,
    max_retries: int,
    base_url: str,
) -> ChatOpenAI:
    api_key = _require_api_key("DASHSCOPE_API_KEY")
    return ChatOpenAI(
        model=QWEN_MODEL,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        extra_body=_thinking_extra_body("qwen", thinking_enabled=thinking_enabled),
        use_responses_api=False,
    )


@lru_cache(maxsize=16)
def _get_llm_cached(
    provider: str,
    thinking_enabled: bool,
    timeout: float,
    max_retries: int,
    base_url: str,
) -> Any:
    """按提供商与思考开关缓存客户端。"""
    if provider == "qwen":
        return _build_qwen_llm(
            thinking_enabled=thinking_enabled,
            timeout=timeout,
            max_retries=max_retries,
            base_url=base_url,
        )
    return _build_deepseek_llm(
        thinking_enabled=thinking_enabled,
        timeout=timeout,
        max_retries=max_retries,
    )


def _cached_client(*, thinking_enabled: bool) -> Any:
    provider = get_llm_provider()
    base_url = _qwen_base_url() if provider == "qwen" else ""
    return _get_llm_cached(
        provider,
        thinking_enabled,
        llm_timeout_sec(),
        llm_max_retries(),
        base_url,
    )


def get_llm() -> Any:
    """自由文本调用（汇总等）；可随 Dashboard 开关启用思考模式。"""
    return _cached_client(thinking_enabled=is_thinking_enabled())


def get_structured_llm() -> Any:
    """结构化 JSON 输出（rewrite/generate_sql/分解/路由/记忆等）。

    DeepSeek 思考模式与 LangChain ``with_structured_output`` 不兼容
    （API 返回 ``Thinking mode does not support this tool_choice``）；
    qwen3.8-max 默认开思考，思考态也不支持强制 tool_choice。
    因此结构化步骤始终关闭思考模式。
    """
    return _cached_client(thinking_enabled=False)


def _structured_output_kwargs(*, model: Any | None) -> dict[str, Any]:
    if model is not None:
        return {}
    if get_llm_provider() == "qwen":
        return {"method": "json_schema"}
    return {}


def invoke_chat(messages: Any, *, model: Any | None = None) -> str:
    """调用自由文本模型一次，返回最终作答字符串。

    ``model`` 非空时用注入模型（测试），否则 ``get_llm()``。
    """
    llm = model if model is not None else get_llm()
    started = time.perf_counter()
    try:
        resp = _call_invoke(llm, messages)
        logger.info(
            "event=llm_call kind=ok structured=0 elapsed_ms=%.0f",
            (time.perf_counter() - started) * 1000,
        )
        return _extract_chat_text(resp)
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
    Qwen 走 ``method="json_schema"``；DeepSeek 保持 LangChain 默认，避免回归。
    """
    llm = model if model is not None else get_structured_llm()
    started = time.perf_counter()
    try:
        result = _call_invoke(
            llm.with_structured_output(schema, **_structured_output_kwargs(model=model)),
            messages,
        )
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
