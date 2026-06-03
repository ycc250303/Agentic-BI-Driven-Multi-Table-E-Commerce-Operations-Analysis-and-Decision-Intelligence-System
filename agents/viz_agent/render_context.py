"""渲染层可选扩展数据（预测曲线、对比词云等）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RenderExtras:
    forecast: dict[str, Any] | None = None
    wordcloud_compare: dict[str, dict[str, int]] | None = None
    value_format: str = "auto"
    color_column: str | None = None
    subtitle: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
