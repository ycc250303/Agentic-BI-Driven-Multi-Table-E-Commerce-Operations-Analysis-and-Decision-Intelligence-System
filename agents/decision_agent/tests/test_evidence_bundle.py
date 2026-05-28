from __future__ import annotations

import json
from pathlib import Path

from agents.decision_agent.tools.build_evidence_bundle import build_evidence_bundle


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_case(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_bundle_contains_delivery_signals():
    bundle = build_evidence_bundle(load_case("high_delivery_risk.json"))
    assert bundle.query_goal
    assert bundle.signals
    assert any(signal.domain == "delivery" for signal in bundle.signals)


def test_bundle_contains_forecast_signal():
    bundle = build_evidence_bundle(load_case("forecast_slowdown.json"))
    assert any(signal.domain == "forecast" for signal in bundle.signals)
