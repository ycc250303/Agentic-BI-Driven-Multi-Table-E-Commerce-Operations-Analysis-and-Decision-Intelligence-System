from __future__ import annotations

import json

from agents.common.paths import load_config_text
from agents.common.prompts import compose_system_prompt_parts
from ..schemas import DecisionResult, EvidenceBundle, ScoredProblem


def build_system_prompt() -> str:
    """叙述层 system：护栏 + 决策规则 + 输出格式，均来自 config/decision_agent/。"""
    return compose_system_prompt_parts(
        "# 核心规则\n\n" + load_config_text("decision_agent", "system_core.md"),
        "# 决策规则\n\n" + load_config_text("decision_agent", "decision_rules.md"),
        "# 输出格式\n\n" + load_config_text("decision_agent", "output_schema.md"),
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
