from __future__ import annotations

from agents.sql_agent.tools.sql_format_rules import (
    query_sql_format_ok,
    read_only_select_ok,
)


def test_format_ok_uppercase_select_without_backticks():
    sql = "SELECT sales_month, total_gmv FROM mv_monthly_sales LIMIT 5"
    assert query_sql_format_ok(sql) is True


def test_format_rejects_lowercase_select():
    assert query_sql_format_ok("select 1") is False


def test_format_rejects_semicolon():
    assert query_sql_format_ok("SELECT 1; SELECT 2") is False


def test_format_rejects_backticks():
    assert query_sql_format_ok("SELECT `sales_month` FROM mv_monthly_sales") is False


def test_read_only_allows_select():
    ok, reason = read_only_select_ok(
        "SELECT sales_month FROM mv_monthly_sales LIMIT 5"
    )
    assert ok is True
    assert reason == ""


def test_read_only_rejects_insert():
    ok, reason = read_only_select_ok("INSERT INTO t VALUES (1)")
    assert ok is False
    assert "只读" in reason or "SELECT" in reason


def test_read_only_rejects_drop_inside_select():
    ok, reason = read_only_select_ok("SELECT * FROM t DROP TABLE x")
    assert ok is False
    assert "高风险" in reason or "只读" in reason
