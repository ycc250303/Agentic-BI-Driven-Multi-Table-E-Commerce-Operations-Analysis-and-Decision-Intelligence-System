"""文件 Prompt 的读取、严格渲染与版本哈希。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from string import Formatter
from typing import Any


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    """一次 Prompt 渲染结果。

    - name：相对 config/prompts 的模板名，不含 .md
    - content：替换变量后的正文
    - version：模板原文 SHA-256 的前 12 位，不含填入的变量值
    """

    name: str
    content: str
    version: str


def render_prompt(
    name: str,
    variables: dict[str, Any],
    *,
    config_dir: Path = Path("config"),
) -> RenderedPrompt:
    """读取并严格渲染一份 Prompt。

    输入：
    - name：相对 config/prompts，不含 .md，可含子目录
    - variables：键必须与模板占位符完全一致
    - config_dir：配置根目录，默认 config

    输出：
    - 渲染结果：缺少变量或出现未知变量时抛 ``ValueError``
    """

    template = load_prompt(name, config_dir=config_dir)
    expected = {
        field_name for _, field_name, _, _ in Formatter().parse(template) if field_name is not None
    }
    supplied = set(variables)
    missing = expected - supplied
    unexpected = supplied - expected
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"缺少变量: {', '.join(sorted(missing))}")
        if unexpected:
            details.append(f"未知变量: {', '.join(sorted(unexpected))}")
        raise ValueError("；".join(details))

    content = template.format_map(variables)
    version = sha256(template.encode("utf-8")).hexdigest()[:12]
    return RenderedPrompt(name=name, content=content, version=version)


@lru_cache(maxsize=64)
def load_prompt(name: str, *, config_dir: Path = Path("config")) -> str:
    """读取一份 Prompt 模板原文。

    输入：
    - name：相对 config_dir/prompts，不含 .md，可含子目录
    - config_dir：配置根目录，默认 config

    约束：
    - 解析后的路径必须仍在 prompts 根目录内
    - 结果按 name 与 config_dir 缓存

    输出：
    - 模板原文：去掉首尾空白
    - 路径越界：抛 ``ValueError``
    - 文件不存在：抛 ``FileNotFoundError``
    """

    prompt_root = (config_dir / "prompts").resolve()
    candidate = (prompt_root / f"{name}.md").resolve()
    if candidate != prompt_root and prompt_root not in candidate.parents:
        raise ValueError("Prompt 路径不能逃逸 config/prompts")
    if not candidate.is_file():
        raise FileNotFoundError(f"Prompt 不存在: {candidate}")
    return candidate.read_text(encoding="utf-8").strip()


def clear_prompt_cache() -> None:
    """清空 ``load_prompt`` 的读取缓存。

    输入：
    - 无

    输出：
    - 无：测试改写模板后调用，避免继续命中旧正文
    """

    load_prompt.cache_clear()
