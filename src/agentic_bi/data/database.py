"""MySQL 只读连接、EXPLAIN、超时与结果预算。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from pydantic import JsonValue
from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from agentic_bi.core.settings import Settings


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """EXPLAIN 提取出的稳定计划信息。"""

    estimated_rows: int | None


@dataclass(frozen=True, slots=True)
class QueryExecution:
    """受预算约束的查询执行结果。"""

    columns: tuple[str, ...]
    rows: tuple[dict[str, JsonValue], ...]
    returned_row_count: int
    truncated: bool
    data_snapshot: str


class DatabaseUnavailableError(RuntimeError):
    """数据库认证、连接或连接中断。"""


class QueryExecutionError(RuntimeError):
    """可安全反馈给 SQL 修复节点的执行错误。"""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class QueryBudgetError(RuntimeError):
    """查询结果超过硬预算。"""


class ReadOnlyDatabase:
    """只使用在线只读账号执行查询。"""

    def __init__(self, settings: Settings) -> None:
        user, password = settings.readonly_credentials()
        url = URL.create(
            "mysql+pymysql",
            username=user,
            password=password.get_secret_value(),
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            query={"charset": "utf8mb4"},
        )
        self._settings = settings
        self._engine: Engine = create_engine(
            url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle_seconds,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": settings.db_connect_timeout_seconds,
                "read_timeout": max(1, settings.sql_timeout_ms // 1000 + 1),
            },
        )
        self._snapshot_id: str | None = None

    def explain(self, sql: str) -> QueryPlan:
        """执行 EXPLAIN FORMAT=JSON，不执行正文查询。"""
        try:
            with self._engine.connect() as connection:
                self._set_timeout(connection)
                result = connection.exec_driver_sql(f"EXPLAIN FORMAT=JSON {sql}")
                raw: Any = result.scalar_one()
        except DBAPIError as exc:
            raise self._translate_db_error(exc) from exc
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError("数据库 EXPLAIN 调用失败") from exc

        try:
            plan = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, json.JSONDecodeError) as exc:
            raise QueryExecutionError(
                "数据库返回了无法解析的 EXPLAIN 结果",
                retryable=False,
            ) from exc

        return QueryPlan(estimated_rows=_maximum_estimated_rows(plan))

    def execute(self, sql: str) -> QueryExecution:
        """执行只读 SQL，并限制行数和序列化字节数。"""
        try:
            with self._engine.connect() as connection:
                self._set_timeout(connection)
                result = connection.exec_driver_sql(sql)
                column_names = result.keys()
                columns = tuple(str(name) for name in column_names)
                raw_rows = result.fetchmany(self._settings.sql_max_rows + 1)
        except DBAPIError as exc:
            raise self._translate_db_error(exc) from exc
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError("数据库查询调用失败") from exc

        truncated = len(raw_rows) > self._settings.sql_max_rows
        selected_rows = raw_rows[: self._settings.sql_max_rows]
        rows: list[dict[str, JsonValue]] = []
        result_bytes = 0

        for raw_row in selected_rows:
            normalized = {column: _normalize_value(raw_row._mapping[column]) for column in columns}
            result_bytes += len(
                json.dumps(
                    normalized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if result_bytes > self._settings.sql_max_result_bytes:
                raise QueryBudgetError("查询结果超过最大字节预算")
            rows.append(normalized)

        return QueryExecution(
            columns=columns,
            rows=tuple(rows),
            returned_row_count=len(rows),
            truncated=truncated,
            data_snapshot=self.snapshot_id(),
        )

    def snapshot_id(self) -> str:
        """生成与订单主表状态相关的数据快照标识。"""
        if self._snapshot_id is not None:
            return self._snapshot_id

        sql = (
            "SELECT COUNT(*) AS row_count, "
            "MAX(order_purchase_timestamp) AS max_purchase_time "
            "FROM orders"
        )
        try:
            with self._engine.connect() as connection:
                self._set_timeout(connection)
                row = connection.exec_driver_sql(sql).one()._mapping
        except DBAPIError as exc:
            raise self._translate_db_error(exc) from exc
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError("数据库快照读取失败") from exc

        maximum = _normalize_value(row["max_purchase_time"])
        self._snapshot_id = f"orders:{row['row_count']}:{maximum}"
        return self._snapshot_id

    def close(self) -> None:
        """释放连接池。"""
        self._engine.dispose()

    def _set_timeout(self, connection: Any) -> None:
        timeout = int(self._settings.sql_timeout_ms)
        connection.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {timeout}")

    @staticmethod
    def _translate_db_error(exc: DBAPIError) -> RuntimeError:
        code: int | None = None
        arguments = getattr(exc.orig, "args", ())
        if arguments and isinstance(arguments[0], int):
            code = arguments[0]

        if code in {1045, 1049, 2003, 2006, 2013} or exc.connection_invalidated:
            return DatabaseUnavailableError("数据库连接或认证不可用")

        messages = {
            1054: "SQL 引用了不存在的列",
            1064: "SQL 语法错误",
            1111: "SQL 聚合函数使用位置不合法",
            1146: "SQL 引用了不存在的表或视图",
            1241: "SQL 子查询返回列数不正确",
            1242: "SQL 标量子查询返回多行",
            3024: "SQL 执行超过数据库超时",
        }
        message = (
            messages.get(code, "数据库拒绝执行当前查询")
            if code is not None
            else "数据库拒绝执行当前查询"
        )
        retryable = code in {1054, 1064, 1111, 1241, 1242, 3024}
        return QueryExecutionError(message, retryable=retryable)


def _normalize_value(value: Any) -> JsonValue:
    """把数据库值转换为可持久化的 JSON 值。"""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _maximum_estimated_rows(value: Any) -> int | None:
    """递归提取 EXPLAIN JSON 中最大的行数估算。"""
    estimates: list[int] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in {
                    "rows",
                    "rows_examined_per_scan",
                    "rows_produced_per_join",
                } and isinstance(child, int | float):
                    estimates.append(int(child))
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return max(estimates) if estimates else None
