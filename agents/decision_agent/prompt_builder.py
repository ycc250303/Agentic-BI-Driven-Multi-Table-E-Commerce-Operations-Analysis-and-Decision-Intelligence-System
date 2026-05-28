from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .schemas import DecisionResult, EvidenceBundle, ScoredProblem


def _project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config" / "decision_agent").exists():
            return parent
    raise RuntimeError("未找到项目根目录下的 config/decision_agent 目录。")


@lru_cache(maxsize=8)
def _load_prompt(name: str) -> str:
    prompt_path = _project_root() / "config" / "decision_agent" / name
    return prompt_path.read_text(encoding="utf-8")


def build_system_prompt() -> str:
    return "\n\n".join(
        [
            "# 核心规则",
            _load_prompt("system_core.md"),
            "# 决策规则",
            _load_prompt("decision_rules.md"),
            "# 输出格式",
            _load_prompt("output_schema.md"),
        ]
    )


def build_human_prompt(
    bundle: EvidenceBundle,
    scored_problems: list[ScoredProblem],
    structured_result: DecisionResult,
) -> str:
    return "\n\n".join(
        [
            "请基于以下结构化证据与规则输出最终业务建议。",
            "## Evidence Bundle",
            bundle.model_dump_json(indent=2, ensure_ascii=False),
            "## Scored Problems",
            json.dumps(
                [problem.model_dump(mode="json") for problem in scored_problems],
                indent=2,
                ensure_ascii=False,
            ),
            "## Structured Draft",
            structured_result.model_dump_json(indent=2, ensure_ascii=False),
        ]
    )
