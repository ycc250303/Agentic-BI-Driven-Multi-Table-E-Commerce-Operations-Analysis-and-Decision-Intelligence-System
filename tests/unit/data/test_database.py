"""只读数据库驱动转义测试。"""

from __future__ import annotations

from agentic_bi.data.database import _escape_dbapi_percent


def test_escape_dbapi_percent_preserves_date_format() -> None:
    sql = "SELECT DATE_FORMAT(order_purchase_timestamp, '%Y-%m') AS sales_month"

    assert _escape_dbapi_percent(sql) == (
        "SELECT DATE_FORMAT(order_purchase_timestamp, '%%Y-%%m') AS sales_month"
    )
