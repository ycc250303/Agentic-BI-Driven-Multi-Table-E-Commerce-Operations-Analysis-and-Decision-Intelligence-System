"""PNG 输出目录（``AGENTIC_BI_VIZ_DIR`` 或包内 ``chart_output/``）。"""

from __future__ import annotations

import os
from pathlib import Path


def viz_output_dir() -> Path:
    raw = os.environ.get("AGENTIC_BI_VIZ_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parents[1] / "chart_output").resolve()
