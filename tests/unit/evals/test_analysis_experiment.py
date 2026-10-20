"""数据分析 Agent 评估数据、规范化与完整 CSV 读取测试。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from evals.analysis_experiment import (
    _canonical_intent,
    _read_csv_rows,
    _same_rows,
    analysis_evaluators,
    load_dataset,
)

from agentic_bi.core.models import ArtifactKind
from agentic_bi.data.metrics import MetricCatalog

_ROOT = Path(__file__).resolve().parents[3]
_FUNCTION_TOKENS = ("date_format", "datediff", "case ", " + ", " / ")
_TABLE_COUNTS = {"easy": 1, "mid": 2}
_CLARIFICATION_CODES = {
    "missing_conversation_context": "missing_context",
    "ambiguous_time": "ambiguous_time",
    "missing_metric": "missing_metric",
    "ambiguous_dimension": "unnamed_grouping",
    "underspecified_multi_metric": "underspecified_ranking",
    "dependent_task_chain": "dependent_steps",
}


def test_local_dataset_balances_difficulty_and_covers_tables() -> None:
    dataset = load_dataset()
    examples = dataset["examples"]
    catalog = MetricCatalog.load(_ROOT / "config" / "metrics.yaml")

    clarification = [example for example in examples if example["split"] == "clarification"]
    answered = [example for example in examples if example["split"] != "clarification"]
    assert all(
        set(example["metadata"]) == {"case_id", "difficulty", "question_family", "tables"}
        for example in answered
    )
    assert all(
        set(example["metadata"]) == {"case_id", "difficulty", "question_family"}
        for example in clarification
    )
    assert len(clarification) == 6
    assert Counter(example["metadata"]["difficulty"] for example in clarification) == {
        "easy": 2,
        "mid": 2,
        "hard": 2,
    }
    assert len({example["metadata"]["question_family"] for example in clarification}) == 6
    for example in clarification:
        assert example["outputs"]["expected_status"] == "needs_input"
        assert (
            example["outputs"]["expected_clarification_code"]
            == _CLARIFICATION_CODES[example["metadata"]["question_family"]]
        )
        assert example["outputs"]["gold_sql"] is None

    assert Counter(example["metadata"]["difficulty"] for example in answered) == {
        "easy": 8,
        "mid": 8,
        "hard": 8,
    }
    covered = {table for example in answered for table in example["metadata"]["tables"]}
    assert covered == {
        "orders",
        "order_items",
        "customers",
        "sellers",
        "products",
        "product_category_name_translation",
        "payments",
        "order_reviews",
    }

    for example in answered:
        difficulty = example["metadata"]["difficulty"]
        table_count = len(example["metadata"]["tables"])
        if difficulty == "hard":
            assert table_count >= 3
        else:
            assert table_count == _TABLE_COUNTS[difficulty]
        assert example["split"] == difficulty
        intent = example["outputs"]["intent"]
        catalog.validate_intent(
            metric_ids=intent["metric_ids"],
            dimensions=intent["dimensions"],
            filter_fields=[item["field"] for item in intent["filters"]],
            sort_by=None,
        )

    for difficulty in ("easy", "mid", "hard"):
        sqls = [
            example["outputs"]["gold_sql"].lower()
            for example in answered
            if example["metadata"]["difficulty"] == difficulty
        ]
        flags = [any(token in sql for token in _FUNCTION_TOKENS) for sql in sqls]
        assert any(flags)
        assert not all(flags)


def test_canonical_intent_ignores_meaningless_order() -> None:
    actual = {
        "metric_ids": ["total_orders", "total_gmv"],
        "dimensions": ["sales_month", "customer_state"],
        "filters": [
            {"field": "customer_state", "operator": "in", "value": ["SP", "RJ"]},
            {"field": "payment_type", "operator": "eq", "value": "credit_card"},
        ],
        "time_range": {"start": "2017-01-01", "end": "2018-01-01"},
    }
    expected = {
        "metric_ids": ["total_gmv", "total_orders"],
        "dimensions": ["customer_state", "sales_month"],
        "filters": [
            {"field": "payment_type", "operator": "eq", "value": "credit_card"},
            {"field": "customer_state", "operator": "in", "value": ["RJ", "SP"]},
        ],
        "time_range": {"end": "2018-01-01", "start": "2017-01-01"},
    }

    assert _canonical_intent(actual) == _canonical_intent(expected)


def test_canonical_intent_preserves_between_boundaries() -> None:
    forward = {
        "metric_ids": ["total_gmv"],
        "dimensions": [],
        "filters": [{"field": "price", "operator": "between", "value": [10, 20]}],
        "time_range": None,
    }
    reversed_bounds = {
        **forward,
        "filters": [{"field": "price", "operator": "between", "value": [20, 10]}],
    }

    assert _canonical_intent(forward) != _canonical_intent(reversed_bounds)


def test_read_csv_rows_returns_all_rows(tmp_path: Path) -> None:
    path = tmp_path / "result.csv"
    path.write_text(
        "customer_state,total_gmv\n" + "".join(f"S{index},{index}.00\n" for index in range(25)),
        encoding="utf-8-sig",
    )
    evidence = SimpleNamespace(
        artifacts=(SimpleNamespace(kind=ArtifactKind.CSV, uri=path.resolve().as_uri()),)
    )

    rows = _read_csv_rows(evidence)

    assert len(rows) == 25
    assert rows[-1] == {"customer_state": "S24", "total_gmv": "24.00"}


def test_same_rows_normalizes_csv_numeric_strings_and_row_order() -> None:
    rows = [
        {"customer_state": "RJ", "total_gmv": "20.00"},
        {"customer_state": "SP", "total_gmv": "123.40"},
    ]
    gold_rows = [
        {"customer_state": "SP", "total_gmv": 123.4},
        {"customer_state": "RJ", "total_gmv": 20},
    ]

    assert _same_rows(rows, gold_rows)


def test_failed_clarification_does_not_receive_execution_accuracy() -> None:
    scores = analysis_evaluators(
        outputs={
            "status": "failed",
            "clarification_code": "missing_metric",
            "clarification_questions": ["请说明用哪个指标衡量表现。"],
            "has_evidence": False,
            "returned_row_count": None,
            "rows": [],
        },
        reference_outputs={
            "expected_status": "needs_input",
            "expected_clarification_code": "missing_metric",
        },
    )
    by_key = {score["key"]: score["score"] for score in scores}

    assert "execution_accuracy" not in by_key
    assert by_key["status_match"] is False
    assert by_key["semantic_match"] is True
    assert by_key["clarification_has_question"] is True
    assert by_key["clarification_has_no_evidence"] is True


def test_valid_clarification_uses_dedicated_scores() -> None:
    scores = analysis_evaluators(
        outputs={
            "status": "needs_input",
            "clarification_code": "missing_metric",
            "clarification_questions": ["请说明用哪个指标衡量表现。"],
            "has_evidence": False,
            "returned_row_count": None,
            "rows": [],
        },
        reference_outputs={
            "expected_status": "needs_input",
            "expected_clarification_code": "missing_metric",
        },
    )
    by_key = {score["key"]: score["score"] for score in scores}

    assert "execution_accuracy" not in by_key
    assert by_key == {
        "status_match": True,
        "semantic_match": True,
        "clarification_has_question": True,
        "clarification_has_no_evidence": True,
    }
