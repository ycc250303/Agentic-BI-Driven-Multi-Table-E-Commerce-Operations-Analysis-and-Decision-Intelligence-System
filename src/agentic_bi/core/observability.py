"""LangSmith 的最小配置与可检索运行元数据。"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from agentic_bi.core.settings import Settings

_SENSITIVE_PARTS = ("api_key", "authorization", "password", "secret", "token")


def configure_langsmith(settings: Settings) -> None:
    """把已验证配置写入 LangSmith 官方环境变量。SDK 只读进程环境，所以在这里集中写入。

    输入：
    - ``langsmith_tracing``：是否启用追踪
    - ``langsmith_project``：项目名
    - ``langsmith_api_key``：API Key，可空
    - ``langsmith_workspace_id``：workspace，可空
    - ``langsmith_endpoint``：区域端点，可空

    输出：
    - 无

    副作用是设置当前进程的 ``LANGSMITH_*``。未提供的可选项不会写入。
    """

    os.environ["LANGSMITH_TRACING"] = str(settings.langsmith_tracing).lower()
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project

    if settings.langsmith_api_key is not None:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
    if settings.langsmith_workspace_id:
        os.environ["LANGSMITH_WORKSPACE_ID"] = settings.langsmith_workspace_id
    if settings.langsmith_endpoint is not None:
        os.environ["LANGSMITH_ENDPOINT"] = str(settings.langsmith_endpoint).rstrip("/")


def build_run_config(
    *,
    run_name: str,
    tags: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
    recursion_limit: int = 30,
) -> RunnableConfig:
    """构造 LangGraph / LangChain 原生运行配置。

    输入：
    - ``run_name``：本次运行名
    - ``tags``：检索标签
    - ``metadata``：可序列化上下文字典，先经过 ``redact_metadata``
    - ``recursion_limit``：默认 30，必须大于 0

    输出：
    - ``RunnableConfig``：含上述四项

    不在这里改 LangSmith 环境变量。
    """

    if recursion_limit < 1:
        raise ValueError("recursion_limit 必须大于 0")
    config: dict[str, Any] = {
        "run_name": run_name,
        "tags": list(tags),
        "metadata": redact_metadata(metadata or {}),
        "recursion_limit": recursion_limit,
    }
    return cast(RunnableConfig, config)


def redact_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """去掉不宜进入 trace 的顶层字段，并限制单个字符串的长度。

    输入：
    - ``metadata``：任意映射，只检查顶层键名，不递归处理嵌套字典

    丢弃键名包含以下片段的项：
    - ``api_key``
    - ``authorization``
    - ``password``
    - ``secret``
    - ``token``

    输出：
    - ``dict``：超过 500 字符的字符串截断，其余值原样保留
    """

    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        normalized = key.lower()
        if any(part in normalized for part in _SENSITIVE_PARTS):
            continue
        if isinstance(value, str) and len(value) > 500:
            safe[key] = f"{value[:500]}…"
        else:
            safe[key] = value
    return safe
