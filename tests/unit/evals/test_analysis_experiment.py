"""数据分析 Agent 评估数据、规范化与完整 CSV 读取测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from evals.analysis_experiment import (
    _canonical_intent,
    _read_csv_rows,
    _same_rows,
    load_dataset,
)

from agentic_bi.core.models import ArtifactKind


def test_local_dataset_uses_native_splits() -> None:
    dataset = load_dataset()

    assert len(dataset["examples"]) == 2
    assert {example["split"] for example in dataset["examples"]} == {
        "smoke",
        "clarification",
    }
    assert all("split" not in example["metadata"] for example in dataset["examples"])


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
