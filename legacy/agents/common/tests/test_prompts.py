from __future__ import annotations

import pytest

from agents.common.prompts import compose_system_prompt, compose_system_prompt_parts


def test_compose_system_prompt_prepends_guardrails():
    text = compose_system_prompt("coordinator_agent", "route_next.md")
    assert "只做什么" in text
    assert "迭代路由" in text
    assert text.index("只做什么") < text.index("迭代路由")


def test_compose_system_prompt_requires_relative():
    with pytest.raises(ValueError):
        compose_system_prompt()


def test_compose_system_prompt_missing_file():
    with pytest.raises(FileNotFoundError):
        compose_system_prompt("does_not_exist.md")


def test_compose_system_prompt_parts_order():
    text = compose_system_prompt_parts("任务正文A", "任务正文B")
    assert text.index("只做什么") < text.index("任务正文A")
    assert text.index("任务正文A") < text.index("任务正文B")


def test_compose_system_prompt_parts_requires_section():
    with pytest.raises(ValueError):
        compose_system_prompt_parts("  ", "")
