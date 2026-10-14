from pathlib import Path

import pytest

from agentic_bi.data.metrics import MetricCatalog
from agentic_bi.data.sql_guard import (
    SqlGuard,
    SqlPolicyError,
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
    assert validated.fingerprint
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

    with pytest.raises(SqlPolicyError, match="不允许访问列"):
        guard.validate(
            "SELECT s.password FROM mv_state_sales AS s",
            allowed_sources=sources,
            maximum_rows=5000,
        )


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
