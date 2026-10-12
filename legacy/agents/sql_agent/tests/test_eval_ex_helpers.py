from __future__ import annotations

from pathlib import Path

from agents.sql_agent.test.eval_db import eval_read_only_ok
from agents.sql_agent.test.eval_ex import (
    filter_literals_ok,
    load_gold_files,
    routing_label,
)
from agents.sql_agent.test.ex_compare import spec_from_intent

_GOLD_DIR = Path("agents/sql_agent/test/gold")


def test_eval_read_only_gate():
    ok, reason = eval_read_only_ok(
        "WITH `t` AS (SELECT 1 AS `x`) SELECT `x` FROM `t`"
    )
    assert ok is True
    assert reason == ""
    assert eval_read_only_ok("SELECT 1")[0] is True
    assert eval_read_only_ok("INSERT INTO t VALUES (1)")[0] is False
    ok_sc, reason_sc = eval_read_only_ok("SELECT 1; SELECT 2")
    assert ok_sc is False
    assert "分号" in reason_sc


def test_load_phase_gold_files():
    cases = load_gold_files(
        [_GOLD_DIR / "phase1.json", _GOLD_DIR / "phase2.json"]
    )
    ids = [c["id"] for c in cases]
    assert "p1-q1" in ids
    assert "p2-oos-forecast" in ids
    phase1 = [c for c in cases if c["split"] == "phase1"]
    assert len(phase1) == 12
    oos = [c for c in cases if c["bucket"] == "oos"]
    assert len(oos) == 3
    for case in cases:
        for intent in case.get("intents") or []:
            spec = spec_from_intent(intent)
            assert spec.key_columns
            if spec.compare == "ordered_topk":
                assert spec.k and spec.k >= 1


def test_load_capability_gold_suites():
    from agents.sql_agent.test.eval_ex import resolve_gold_paths, SUITES

    paths = resolve_gold_paths(None, ["capability"])
    assert [p.name for p in paths] == SUITES["capability"]
    cases = load_gold_files(paths)
    by_split: dict[str, int] = {}
    ids: list[str] = []
    for case in cases:
        split = str(case["split"])
        by_split[split] = by_split.get(split, 0) + 1
        ids.append(str(case["id"]))
        assert case["bucket"] != "oos"
        assert case["intents"]
        for intent in case["intents"]:
            spec = spec_from_intent(intent)
            assert spec.key_columns
            gold_sql = str(intent["gold_sql"]).lstrip().upper()
            assert gold_sql.startswith("SELECT") or gold_sql.startswith("WITH")
    assert by_split == {"smoke": 8, "general": 8, "complex": 8, "extreme": 8}
    assert len(ids) == len(set(ids))
    assert resolve_gold_paths(None, None)[0].name == "phase1.json"


def test_routing_and_filter_helpers():
    assert routing_label(["mv_monthly_sales"], ["mv_monthly_sales"]) == "exact"
    assert routing_label(["mv_monthly_sales"], []) == "missing"
    assert routing_label([], ["mv_state_sales"]) == "extra"
    assert routing_label(
        ["mv_monthly_sales"], ["mv_state_sales"]
    ) == "none"
    assert filter_literals_ok(["SELECT * FROM t WHERE y='2017' AND s='SP'"], ["2017", "SP"])
    assert not filter_literals_ok(["SELECT * FROM t WHERE y='2018'"], ["2017"])


def test_summarize_validate_gold_skips_ex_rates():
    from agents.sql_agent.test.eval_ex import summarize_rows

    rows = [
        {
            "id": "a",
            "gold_ok": True,
            "ex_eligible": False,
            "oos": False,
            "infra_error": None,
        }
    ]
    summary = summarize_rows(rows, validate_gold_only=True)
    assert summary["gold_ok"] is True
    assert "question_ex" not in summary
    assert summary["by_split"] == {}


def test_summarize_ex_by_split():
    from agents.sql_agent.test.eval_ex import summarize_rows

    rows = [
        {
            "id": "smoke-01",
            "split": "smoke",
            "ex_eligible": True,
            "question_pass": True,
            "oos": False,
            "infra_error": None,
            "validity": True,
            "routing": "exact",
            "intents": [{"id": "a", "pass": True}],
        },
        {
            "id": "complex-01",
            "split": "complex",
            "ex_eligible": True,
            "question_pass": False,
            "oos": False,
            "infra_error": None,
            "validity": True,
            "routing": "exact",
            "intents": [{"id": "a", "pass": True}, {"id": "b", "pass": False}],
        },
    ]
    summary = summarize_rows(rows)
    assert summary["by_split"]["smoke"]["question_ex"] == 1.0
    assert summary["by_split"]["complex"]["question_ex"] == 0.0
    assert summary["by_split"]["complex"]["intent_micro_ex"] == 0.5


def test_stability_mean_min_max_and_always_pass():
    from agents.sql_agent.test.eval_ex import _stability

    summaries = [
        {"question_ex": 0.5},
        {"question_ex": 0.7},
        {"question_ex": 0.6},
    ]
    run_rows = [
        [{"id": "a", "ex_eligible": True, "question_pass": True, "infra_error": None}],
        [{"id": "a", "ex_eligible": True, "question_pass": False, "infra_error": None}],
        [{"id": "a", "ex_eligible": True, "question_pass": True, "infra_error": None}],
    ]
    out = _stability(summaries, run_rows)
    assert out["question_ex_min"] == 0.5
    assert out["question_ex_max"] == 0.7
    assert out["question_ex_mean"] == 0.6
    assert out["always_pass_rate"] == 0.0
    assert out["always_pass_denom"] == 1
