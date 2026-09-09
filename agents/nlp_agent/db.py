"""NLP Agent 的轻量 MySQL 查询封装。

设计原则：
- 连接参数只来自根目录 ``db_env``（``AGENTIC_BI_DB_*``），不依赖 sql_agent；
- 仅承担 NLP 自身的固定查询 / 灌库写入，不做 SQL 安全校验，调用者必须传入受控 SQL。
"""

from __future__ import annotations

from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from db_env import json_safe_value, pymysql_config


def _connect() -> pymysql.connections.Connection:
    cfg = pymysql_config(autocommit=False)
    cfg["cursorclass"] = DictCursor
    return pymysql.connect(**cfg)


def query(sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
    """执行只读 SELECT，返回反序列化后的 list[dict]。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall() or []
    finally:
        conn.close()
    return [{k: json_safe_value(v) for k, v in r.items()} for r in rows]


def execute(sql: str, params: tuple | None = None) -> int:
    """执行写入语句（INSERT / UPDATE / DDL），返回受影响行数。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            affected = cur.execute(sql, params or ())
        conn.commit()
    finally:
        conn.close()
    return int(affected)


def executemany(sql: str, rows: list[tuple]) -> int:
    """批量写入，返回 ``rows`` 长度（空列表返回 0）。"""
    if not rows:
        return 0
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)
