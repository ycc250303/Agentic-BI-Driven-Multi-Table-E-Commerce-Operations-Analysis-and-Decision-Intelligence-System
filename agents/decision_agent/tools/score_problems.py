from __future__ import annotations

from ..schemas import EvidenceBundle, ScoredProblem
from .rules import detect_problems_and_score


def score_problems(bundle: EvidenceBundle) -> list[ScoredProblem]:
    return detect_problems_and_score(bundle)
