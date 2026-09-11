from __future__ import annotations

from decimal import Decimal

from agents.sql_agent.test.ex_compare import (
    CompareSpec,
    ResultSet,
    compare_result_sets,
    match_intents,
    values_equal,
)


def _rs(columns: list[str], rows: list[dict]) -> ResultSet:
    return ResultSet(columns=tuple(columns), rows=tuple(rows))


def test_scalar_pass_named_and_tolerance():
    gold = _rs(["gmv_2017"], [{"gmv_2017": Decimal("100.0")}])
    pred = _rs(["gmv_2017"], [{"gmv_2017": 100.00005}])
    spec = CompareSpec(compare="scalar", key_columns=("gmv_2017",), numeric_tol=1e-4)
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is True
    assert reason == ""


def test_scalar_fail_beyond_tolerance():
    gold = _rs(["gmv_2017"], [{"gmv_2017": 100.0}])
    pred = _rs(["gmv_2017"], [{"gmv_2017": 110.0}])
    spec = CompareSpec(compare="scalar", key_columns=("gmv_2017",), numeric_tol=1e-4)
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is False
    assert reason == "unmatched"


def test_scalar_positional_alias():
    gold = _rs(["gmv_2017"], [{"gmv_2017": 10}])
    pred = _rs(["total_gmv"], [{"total_gmv": 10}])
    spec = CompareSpec(compare="scalar", key_columns=("gmv_2017",))
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is True
    assert reason == ""


def test_scalar_row_count_fail():
    gold = _rs(["gmv_2017"], [{"gmv_2017": 1}])
    pred = _rs(
        ["year_month", "total_gmv"],
        [{"year_month": "2017-01", "total_gmv": 1}, {"year_month": "2017-02", "total_gmv": 2}],
    )
    spec = CompareSpec(compare="scalar", key_columns=("gmv_2017",))
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is False
    assert reason == "row_count"


def test_schema_mismatch_when_names_and_arity_differ():
    gold = _rs(["product_category"], [{"product_category": "a"}])
    pred = _rs(["cnt", "n"], [{"cnt": 3, "n": 1}])
    spec = CompareSpec(compare="scalar", key_columns=("product_category",))
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is False
    assert reason == "schema_mismatch"


def test_bag_ignores_order():
    gold = _rs(
        ["year_month", "total_gmv"],
        [{"year_month": "2017-01", "total_gmv": 1}, {"year_month": "2017-02", "total_gmv": 2}],
    )
    pred = _rs(
        ["year_month", "total_gmv"],
        [{"year_month": "2017-02", "total_gmv": 2}, {"year_month": "2017-01", "total_gmv": 1}],
    )
    spec = CompareSpec(compare="bag", key_columns=("year_month", "total_gmv"))
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is True
    assert reason == ""


def test_bag_missing_row_fails():
    gold = _rs(
        ["year_month", "total_gmv"],
        [{"year_month": "2017-01", "total_gmv": 1}, {"year_month": "2017-02", "total_gmv": 2}],
    )
    pred = _rs(["year_month", "total_gmv"], [{"year_month": "2017-01", "total_gmv": 1}])
    spec = CompareSpec(compare="bag", key_columns=("year_month", "total_gmv"))
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is False
    assert reason == "unmatched"


def test_ordered_topk_pass_and_ignore_extra_columns():
    gold = _rs(
        ["product_category", "n"],
        [{"product_category": "a", "n": 9}, {"product_category": "b", "n": 8}],
    )
    pred = _rs(
        ["product_category", "cnt"],
        [
            {"product_category": "a", "cnt": 1},
            {"product_category": "b", "cnt": 1},
            {"product_category": "c", "cnt": 1},
        ],
    )
    spec = CompareSpec(compare="ordered_topk", key_columns=("product_category",), k=2)
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is True
    assert reason == ""


def test_ordered_topk_swap_fails():
    gold = _rs(["product_category"], [{"product_category": "a"}, {"product_category": "b"}])
    pred = _rs(["product_category"], [{"product_category": "b"}, {"product_category": "a"}])
    spec = CompareSpec(compare="ordered_topk", key_columns=("product_category",), k=2)
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is False
    assert reason == "unmatched"


def test_ordered_topk_too_few_rows():
    gold = _rs(["product_category"], [{"product_category": "a"}, {"product_category": "b"}])
    pred = _rs(["product_category"], [{"product_category": "a"}])
    spec = CompareSpec(compare="ordered_topk", key_columns=("product_category",), k=2)
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is False
    assert reason == "too_few_rows"


def test_greedy_second_intent_unmatched_after_first_takes_only_pred():
    intents = [
        {
            "id": "a",
            "compare": "scalar",
            "key_columns": ["v"],
        },
        {
            "id": "b",
            "compare": "scalar",
            "key_columns": ["v"],
        },
    ]
    gold = [
        _rs(["v"], [{"v": 1}]),
        _rs(["v"], [{"v": 2}]),
    ]
    pred_ok = [True]
    pred = [_rs(["v"], [{"v": 1}])]
    rows = match_intents(intents, gold, pred_ok, pred, pred_sql_count=1)
    assert rows[0]["pass"] is True
    assert rows[0]["pred_index"] == 0
    assert rows[1]["pass"] is False
    assert rows[1]["reason"] == "unmatched"


def test_no_pred_sql():
    intents = [{"id": "a", "compare": "scalar", "key_columns": ["v"]}]
    gold = [_rs(["v"], [{"v": 1}])]
    rows = match_intents(intents, gold, [], [], pred_sql_count=0)
    assert rows[0]["pass"] is False
    assert rows[0]["reason"] == "no_pred_sql"


def test_greedy_skips_non_matching_first_sql():
    intents = [
        {"id": "scalar", "compare": "scalar", "key_columns": ["gmv"]},
        {
            "id": "bag",
            "compare": "bag",
            "key_columns": ["year_month", "total_gmv"],
        },
    ]
    gold = [
        _rs(["gmv"], [{"gmv": 10}]),
        _rs(
            ["year_month", "total_gmv"],
            [{"year_month": "2017-01", "total_gmv": 4}],
        ),
    ]
    pred_ok = [True, True]
    pred = [
        _rs(
            ["year_month", "total_gmv"],
            [{"year_month": "2017-01", "total_gmv": 4}],
        ),
        _rs(["gmv"], [{"gmv": 10}]),
    ]
    rows = match_intents(intents, gold, pred_ok, pred, pred_sql_count=2)
    assert rows[0]["pass"] is True
    assert rows[0]["pred_index"] == 1
    assert rows[1]["pass"] is True
    assert rows[1]["pred_index"] == 0


def test_bag_ignores_extra_pred_columns():
    gold = _rs(
        ["year_month", "total_gmv"],
        [{"year_month": "2017-01", "total_gmv": 1}],
    )
    pred = _rs(
        ["year_month", "total_gmv", "total_orders"],
        [{"year_month": "2017-01", "total_gmv": 1, "total_orders": 9}],
    )
    spec = CompareSpec(compare="bag", key_columns=("year_month", "total_gmv"))
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is True
    assert reason == ""


def test_values_equal_none_and_int_float():
    assert values_equal(None, None, 1e-4) is True
    assert values_equal(10, 10.0, 1e-4) is True
    assert values_equal("SP", "SP", 1e-4) is True
    assert values_equal("SP", "sp", 1e-4) is False


def test_scalar_synonym_ignores_extra_measure():
    gold = _rs(["top_state_2017"], [{"top_state_2017": "SP"}])
    pred = _rs(
        ["customer_state", "total_gmv"],
        [{"customer_state": "SP", "total_gmv": 99}],
    )
    spec = CompareSpec(compare="scalar", key_columns=("top_state_2017",))
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is True
    assert reason == ""


def test_topk_category_alias():
    gold = _rs(["product_category"], [{"product_category": "a"}, {"product_category": "b"}])
    pred = _rs(
        ["product_category_english", "bad_review_count"],
        [
            {"product_category_english": "a", "bad_review_count": 9},
            {"product_category_english": "b", "bad_review_count": 8},
        ],
    )
    spec = CompareSpec(compare="ordered_topk", key_columns=("product_category",), k=2)
    ok, reason = compare_result_sets(gold, pred, spec)
    assert ok is True
    assert reason == ""


def test_bag_merge_two_pred_sqls():
    intents = [
        {
            "id": "trend",
            "compare": "bag",
            "key_columns": ["year_month", "payment_type", "total_transactions"],
        }
    ]
    gold = [
        _rs(
            ["year_month", "payment_type", "total_transactions"],
            [
                {"year_month": "2017-01", "payment_type": "credit_card", "total_transactions": 1},
                {"year_month": "2017-01", "payment_type": "boleto", "total_transactions": 2},
            ],
        )
    ]
    pred_ok = [True, True]
    pred = [
        _rs(
            ["year_month", "payment_type", "total_transactions"],
            [{"year_month": "2017-01", "payment_type": "credit_card", "total_transactions": 1}],
        ),
        _rs(
            ["year_month", "payment_type", "total_transactions"],
            [{"year_month": "2017-01", "payment_type": "boleto", "total_transactions": 2}],
        ),
    ]
    rows = match_intents(intents, gold, pred_ok, pred, pred_sql_count=2)
    assert rows[0]["pass"] is True

