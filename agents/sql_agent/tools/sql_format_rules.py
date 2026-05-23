"""
SQL 规范与安全相关共享规则。
供 generate_sql / check_sql / execute_sql 统一复用，避免多处实现漂移。
"""

from __future__ import annotations

import re


def normalize_sql(sql: str) -> str:
    s = sql.strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s


def query_sql_format_ok(sql: str) -> bool:
    """
    统一格式约束：
    - 语句以大写 SELECT 开头
    - 单条语句内不允许分号
    - 反引号内标识符必须全小写
    """
    s = sql.strip()
    if not s.startswith("SELECT"):
        return False
    if ";" in s:
        return False
    for m in re.finditer(r"`([^`]*)`", s):
        inner = m.group(1)
        if inner and inner != inner.lower():
            return False
    return True


def read_only_select_ok(sql: str) -> tuple[bool, str]:
    """
    只读安全规则：
    - 仅允许 SELECT
    - 禁止高风险 DDL/DML 片段
    """
    s = normalize_sql(sql)
    if ";" in s:
        return False, "单条 SELECT 内不允许分号"
    if not s.upper().startswith("SELECT"):
        return False, "仅允许 SELECT 查询"

    no_str = re.sub(r"'(?:[^'\\]|\\.)*'", "''", s)
    no_id = re.sub(r"`[^`]*`", "`x`", no_str)
    banned = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|"
        r"GRANT|REVOKE|CALL|EXECUTE|INTO\s+OUTFILE|LOAD\s+DATA)\b",
        re.IGNORECASE,
    )
    if banned.search(no_id):
        return False, "检测到非只读或高风险 SQL 片段"
    return True, ""
