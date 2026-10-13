from pathlib import Path

import pytest

from agentic_bi.core.prompts import clear_prompt_cache, render_prompt


def _write_prompt(config_dir: Path, content: str) -> None:
    prompt_dir = config_dir / "prompts" / "analysis"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "demo.md").write_text(content, encoding="utf-8")


def test_render_prompt_is_strict_and_versioned(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "问题：{question}\n指标：{metric}")

    rendered = render_prompt(
        "analysis/demo",
        {"question": "销售额？", "metric": "revenue"},
        config_dir=tmp_path,
    )

    assert rendered.content == "问题：销售额？\n指标：revenue"
    assert len(rendered.version) == 12


def test_render_prompt_rejects_missing_or_unknown_variables(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "问题：{question}")

    with pytest.raises(ValueError, match="缺少变量: question"):
        render_prompt("analysis/demo", {}, config_dir=tmp_path)

    with pytest.raises(ValueError, match="未知变量: extra"):
        render_prompt(
            "analysis/demo",
            {"question": "销售额？", "extra": "x"},
            config_dir=tmp_path,
        )


def test_render_prompt_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不能逃逸"):
        render_prompt("../../secret", {}, config_dir=tmp_path)


def teardown_function() -> None:
    clear_prompt_cache()
