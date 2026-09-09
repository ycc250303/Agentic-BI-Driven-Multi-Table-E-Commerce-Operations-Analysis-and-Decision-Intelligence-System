"""拼装 LLM system prompt：共用防注入规则 + 任务文件。

``paths.load_config_text`` 只读 ``config/``；本模块负责前置 ``prompt_guardrails.md``。
模型看不到文件路径，必须把全文注入 system 消息。
"""

from __future__ import annotations

from agents.common.paths import load_config_text

_GUARDRAILS_HEADING = "# 共用安全与任务边界"


def compose_system_prompt(*relative: str) -> str:
    """始终前置 ``prompt_guardrails.md``，再拼接 ``config/<relative>``。

    示例：``compose_system_prompt("coordinator_agent", "route_next.md")``。
    ``relative`` 为空时抛 ``ValueError``；文件缺失时抛 ``FileNotFoundError``。
    """
    if not relative:
        raise ValueError("compose_system_prompt 需要至少一个相对路径片段")
    return compose_system_prompt_parts(load_config_text(*relative))


def compose_system_prompt_parts(*sections: str) -> str:
    """前置共用防注入全文，再按序拼接已读好的任务片段。

    用于 SQL / 决策等需要拼接多份 config 的场景。
    ``sections`` 为空时抛 ``ValueError``。
    """
    nonempty = [s.strip() for s in sections if (s or "").strip()]
    if not nonempty:
        raise ValueError("compose_system_prompt_parts 需要至少一个任务片段")
    guardrails = load_config_text("prompt_guardrails.md")
    return "\n\n".join([f"{_GUARDRAILS_HEADING}\n\n{guardrails}", *nonempty])
