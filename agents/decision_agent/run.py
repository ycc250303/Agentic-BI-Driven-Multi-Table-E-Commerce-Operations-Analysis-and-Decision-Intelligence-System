from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters import decision_inputs_from_state, merge_decision_result_to_state
from .schemas import DecisionInputs
from .service import answer_decision, collect_input_warnings, run_decision
from .state import BIState


def run_decision_state(state: BIState, *, model=None) -> BIState:
    """Compatibility path for orchestrator-style state input/output."""
    inputs = decision_inputs_from_state(state)
    decision_result = run_decision(inputs, model=model)
    warnings = collect_input_warnings(inputs)
    return merge_decision_result_to_state(
        state,
        decision_result,
        warnings=warnings,
    )


class DecisionAgent:
    """Backward-compatible wrapper around the state compatibility path."""

    def __init__(self, model=None):
        self.model = model

    def run(self, state: BIState) -> BIState:
        return run_decision_state(state, model=self.model)


def decision_node(state: BIState) -> BIState:
    """Legacy state-compatible function entrypoint."""
    return run_decision_state(state)


def _load_fixture(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("fixture 内容必须是 JSON object。")
    return data


def _build_inputs_from_fixture(data: dict) -> DecisionInputs:
    if "analysis_result" in data or "user_query" in data:
        return decision_inputs_from_state(data)
    return DecisionInputs.model_validate(data)


def _write_output(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run decision agent with a fixture.")
    parser.add_argument("--fixture", required=True, help="Path to fixture JSON.")
    parser.add_argument(
        "--mode",
        choices=["state", "result", "answer"],
        default="answer",
        help="state: return state patch result; result: return DecisionResult; answer: return final string",
    )
    args = parser.parse_args()

    data = _load_fixture(args.fixture)
    if args.mode == "state":
        result = decision_node(data)
        _write_output(json.dumps(result, indent=2, ensure_ascii=False))
        return

    inputs = _build_inputs_from_fixture(data)
    decision_result = run_decision(inputs)
    if args.mode == "result":
        _write_output(
            json.dumps(decision_result.model_dump(mode="json"), indent=2, ensure_ascii=False)
        )
        return

    _write_output(decision_result.narrative_answer)


if __name__ == "__main__":
    main()
