from __future__ import annotations

from ..rules import detect_problems_and_score
from ..schemas import EvidenceBundle, ScoredProblem


def score_problems(bundle: EvidenceBundle) -> list[ScoredProblem]:
    return detect_problems_and_score(bundle)
