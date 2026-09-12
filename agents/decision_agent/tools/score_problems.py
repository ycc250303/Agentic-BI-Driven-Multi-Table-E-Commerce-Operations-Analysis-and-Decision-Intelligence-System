from __future__ import annotations

from ..schemas import EvidenceBundle, ScoredProblem
from .rules import detect_problems_and_score


def score_problems(bundle: EvidenceBundle) -> list[ScoredProblem]:
    """证据包 → 优先问题列表。打分逻辑在 rules.detect_problems_and_score。"""
    return detect_problems_and_score(bundle)
