"""
Decision Intelligence Agent 的轻量 MySQL 查询封装。

直接复用 SQL Agent 的环境变量与值序列化逻辑（`AGENTIC_BI_DB_*`），
仅在本 Agent 自身需要补充查询（预测、评论洞察、What-if）时使用。
不承担 Data Analysis Agent 的常规查询职责。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

# 复用 sql_agent 中已有的环境变量解析与值序列化函数，避免重复实现
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SQL_AGENT_DIR = _PROJECT_ROOT / "agents" / "sql_agent"
if str(_SQL_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_SQL_AGENT_DIR))

from tools.execute_sql import _db_config_from_env, _json_safe_value  # noqa: E402


def query(sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
    """执行只读 SELECT，返回反序列化后的 list[dict]。

    本函数不做安全校验，调用者必须传入受控 SQL（仅用于 Decision Agent 内部固定查询）。
    """
    cfg = _db_config_from_env()
    cfg.setdefault("cursorclass", DictCursor)
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall() or []
    finally:
        conn.close()
    return [{k: _json_safe_value(v) for k, v in r.items()} for r in rows]
