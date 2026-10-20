from pathlib import Path

import pytest

from agentic_bi.data.metrics import MetricCatalog
from agentic_bi.data.sql_guard import (
    SqlGuard,
    SqlPolicyError,
    SqlPolicyViolation,
    load_sql_policy,
)


def _guard_and_sources() -> tuple[SqlGuard, dict[str, frozenset[str]]]:
    catalog = MetricCatalog.load(Path("config/metrics.yaml"))
    policy = load_sql_policy(Path("config/sql_policy.yaml"))
    sources = catalog.allowed_sources(
        metric_ids=("total_gmv",),
        dimensions=("customer_state",),
    )
    return SqlGuard(policy), sources


def test_guard_accepts_read_only_aggregate() -> None:
    guard, sources = _guard_and_sources()

    validated = guard.validate(
        """
        SELECT customer_state, SUM(total_gmv) AS total_gmv
        FROM mv_state_sales
        WHERE sales_month >= '2017-01'
          AND sales_month < '2018-01'
        GROUP BY customer_state
        ORDER BY total_gmv DESC
        LIMIT 10
        """,
        allowed_sources=sources,
        maximum_rows=5000,
    )

    assert validated.sources == ("mv_state_sales",)
    assert "LIMIT 10" in validated.sql.upper()


def test_guard_rejects_multiple_statements() -> None:
    guard, sources = _guard_and_sources()

    with pytest.raises(SqlPolicyError, match="一条 SQL"):
        guard.validate(
            "SELECT 1; SELECT 2",
            allowed_sources=sources,
            maximum_rows=5000,
        )


def test_guard_rejects_write_statement() -> None:
    guard, sources = _guard_and_sources()

    with pytest.raises(SqlPolicyError, match="SELECT"):
        guard.validate(
            "DELETE FROM orders",
            allowed_sources=sources,
            maximum_rows=5000,
        )


def test_guard_rejects_unknown_source() -> None:
    guard, sources = _guard_and_sources()

    with pytest.raises(SqlPolicyError, match="白名单"):
        guard.validate(
            "SELECT secret FROM internal_users",
            allowed_sources=sources,
            maximum_rows=5000,
        )


def test_guard_rejects_unknown_column() -> None:
    guard, sources = _guard_and_sources()

    with pytest.raises(SqlPolicyError, match="不包含列"):
        guard.validate(
            "SELECT s.password FROM mv_state_sales AS s",
            allowed_sources=sources,
            maximum_rows=5000,
        )


def test_guard_checks_unqualified_column_against_actual_source() -> None:
    catalog = MetricCatalog.load(Path("config/metrics.yaml"))
    guard = SqlGuard(load_sql_policy(Path("config/sql_policy.yaml")))
    sources = catalog.allowed_sources(
        metric_ids=("total_orders",),
        dimensions=("seller_state",),
    )

    with pytest.raises(SqlPolicyError) as captured:
        guard.validate(
            """
            SELECT seller_state, COUNT(DISTINCT order_id) AS total_orders
            FROM mv_seller_perf
            GROUP BY seller_state
            """,
            allowed_sources=sources,
            maximum_rows=5000,
        )

    error = captured.value
    assert error.violation == SqlPolicyViolation.UNKNOWN_COLUMN
    assert error.context["sources"] == ["mv_seller_perf"]
    assert error.context["column"] == "order_id"
    assert "total_orders" in error.context["allowed_columns"]


def test_guard_requires_qualifier_for_ambiguous_column() -> None:
    guard, sources = _guard_and_sources()

    with pytest.raises(SqlPolicyError) as captured:
        guard.validate(
            """
            SELECT order_id
            FROM orders AS o
            JOIN order_items AS oi ON o.order_id = oi.order_id
            """,
            allowed_sources=sources,
            maximum_rows=5000,
        )

    error = captured.value
    assert error.violation == SqlPolicyViolation.AMBIGUOUS_COLUMN
    assert error.context == {
        "column": "order_id",
        "candidate_qualifiers": ["o", "oi"],
    }


def test_guard_accepts_cte_output_column() -> None:
    guard, sources = _guard_and_sources()

    validated = guard.validate(
        """
        WITH delivered_orders AS (
            SELECT o.order_id
            FROM orders AS o
            WHERE o.order_status = 'delivered'
        )
        SELECT d.order_id
        FROM delivered_orders AS d
        """,
        allowed_sources=sources,
        maximum_rows=5000,
    )

    assert validated.sources == ("orders",)


def test_guard_rejects_column_not_projected_by_cte() -> None:
    guard, sources = _guard_and_sources()

    with pytest.raises(SqlPolicyError) as captured:
        guard.validate(
            """
            WITH delivered_orders AS (
                SELECT o.order_id
                FROM orders AS o
            )
            SELECT d.order_status
            FROM delivered_orders AS d
            """,
            allowed_sources=sources,
            maximum_rows=5000,
        )

    error = captured.value
    assert error.violation == SqlPolicyViolation.UNKNOWN_COLUMN
    assert error.context == {
        "source": "d",
        "column": "order_status",
        "allowed_columns": ["order_id"],
    }


def test_guard_rejects_column_not_projected_by_subquery() -> None:
    guard, sources = _guard_and_sources()

    with pytest.raises(SqlPolicyError) as captured:
        guard.validate(
            """
            SELECT delivered.order_status
            FROM (
                SELECT o.order_id
                FROM orders AS o
            ) AS delivered
            """,
            allowed_sources=sources,
            maximum_rows=5000,
        )

    error = captured.value
    assert error.violation == SqlPolicyViolation.UNKNOWN_COLUMN
    assert error.context == {
        "source": "delivered",
        "column": "order_status",
        "allowed_columns": ["order_id"],
    }


def test_guard_rejects_select_star() -> None:
    guard, sources = _guard_and_sources()

    with pytest.raises(SqlPolicyError, match=r"SELECT \*"):
        guard.validate(
            "SELECT * FROM mv_state_sales",
            allowed_sources=sources,
            maximum_rows=5000,
        )


def test_guard_allows_count_star() -> None:
    guard, sources = _guard_and_sources()

    validated = guard.validate(
        "SELECT COUNT(*) AS total_orders FROM orders",
        allowed_sources=sources,
        maximum_rows=5000,
    )

    assert "COUNT(*)" in validated.sql.upper()


def test_guard_adds_hard_limit() -> None:
    guard, sources = _guard_and_sources()

    validated = guard.validate(
        "SELECT customer_state FROM mv_state_sales",
        allowed_sources=sources,
        maximum_rows=5000,
    )

    assert "LIMIT 5001" in validated.sql.upper()


def test_plan_budget_is_source_specific() -> None:
    guard, _ = _guard_and_sources()

    with pytest.raises(SqlPolicyError, match="超过预算"):
        guard.validate_plan(
            estimated_rows=600_000,
            sources=("orders",),
        )
