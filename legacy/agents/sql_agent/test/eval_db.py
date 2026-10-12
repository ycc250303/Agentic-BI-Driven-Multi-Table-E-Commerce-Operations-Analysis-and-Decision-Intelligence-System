"""评测专用只读执行器：允许 WITH CTE，不走产品 check_sql 的 SELECT 开头约束。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from db_env import pymysql_config
from agents.sql_agent.tools.sql_format_rules import normalize_sql

_BANNED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|"
    r"GRANT|REVOKE|CALL|EXECUTE|INTO\s+OUTFILE|LOAD\s+DATA)\b",
    re.IGNORECASE,
)


@dataclass
class QueryResult:
    sql: str
    ok: bool
    columns: list[str]
    rows: list[dict[str, Any]]
    error: str | None = None


def eval_read_only_ok(sql: str) -> tuple[bool, str]:
    """评测闸门：单条 SELECT 或 WITH；禁止分号与写操作。"""
    s = normalize_sql(sql)
    if not s:
        return False, "SQL 为空"
    if ";" in s:
        return False, "单条语句内不允许分号"
    head = s.lstrip().upper()
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        return False, "仅允许 SELECT 或 WITH"
    no_str = re.sub(r"'(?:[^'\\]|\\.)*'", "''", s)
    no_id = re.sub(r"`[^`]*`", "`x`", no_str)
    if _BANNED.search(no_id):
        return False, "检测到非只读或高风险 SQL 片段"
    return True, ""


def execute_eval_sql(sql: str, *, connection: Any | None = None) -> QueryResult:
    """执行一条只读 SQL，返回全部行（无产品侧 5000 行截断）。"""
    ok, reason = eval_read_only_ok(sql)
    if not ok:
        return QueryResult(sql=sql, ok=False, columns=[], rows=[], error=reason)

    own_conn = connection is None
    conn = connection
    try:
        if own_conn:
            cfg = pymysql_config(autocommit=True)
            cfg["cursorclass"] = DictCursor
            conn = pymysql.connect(**cfg)
        assert conn is not None
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = list(cur.fetchall())
            description = cur.description or []
            columns = [str(col[0]) for col in description]
        return QueryResult(sql=sql, ok=True, columns=columns, rows=rows, error=None)
    except Exception as e:
        return QueryResult(sql=sql, ok=False, columns=[], rows=[], error=str(e))
    finally:
        if own_conn and conn is not None:
            conn.close()
