"""仓库根定位与 ``config/`` 文本读取。

只读文件，不拼业务 Prompt。YAML / 词典解析仍由调用方负责。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


def project_root() -> Path:
    """从本文件向上找同时含 ``config/`` 与 ``agents/`` 的仓库根。"""
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / "config").is_dir() and (parent / "agents").is_dir():
            return parent
    raise RuntimeError("未找到仓库根（需同时包含 config/ 与 agents/）")


@lru_cache(maxsize=64)
def load_config_text(*relative: str) -> str:
    """读取 ``project_root()/config/<relative>`` 的 UTF-8 文本。

    示例：``load_config_text("coordinator_agent", "route_next.md")``。
    文件不存在时抛 ``FileNotFoundError``。
    """
    if not relative:
        raise ValueError("load_config_text 需要至少一个相对路径片段")
    path = project_root() / "config" / Path(*relative)
    if not path.is_file():
        raise FileNotFoundError(f"未找到配置文件：{path}")
    return path.read_text(encoding="utf-8")
