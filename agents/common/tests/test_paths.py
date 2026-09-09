from __future__ import annotations

import pytest

from agents.common.paths import load_config_text, project_root


def test_project_root_contains_config_and_agents():
    root = project_root()
    assert (root / "config").is_dir()
    assert (root / "agents").is_dir()
    assert (root / "db_env.py").is_file()


def test_load_config_text_reads_guardrails():
    text = load_config_text("prompt_guardrails.md")
    assert "只做什么" in text


def test_load_config_text_missing_file():
    with pytest.raises(FileNotFoundError):
        load_config_text("does_not_exist.md")


def test_load_config_text_requires_relative():
    with pytest.raises(ValueError):
        load_config_text()
