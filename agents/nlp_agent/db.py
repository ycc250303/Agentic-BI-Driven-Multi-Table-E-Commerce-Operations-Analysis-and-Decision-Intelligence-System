"""
NLP Agent 的轻量 MySQL 查询封装。

设计原则：
- **不依赖** `agents.decision_agent`：让 NLP Agent 在 decision 被重构 / 删除时仍能独立工作；
- 复用 `agents/sql_agent/tools/execute_sql.py` 中已实现的环境变量解析（`AGENTIC_BI_DB_*`）
  与值序列化函数（`_db_config_from_env` / `_json_safe_value`），避免重复实现；
- 自带 `.env` 加载：当 NLP Agent 作为 CLI 直接调用（`python -m agents.nlp_agent.tools.*`）时，
  仍能从项目根目录自动读取 `.env`，无需依赖 sql_agent 的 `get_llm()` 副作用；
- 仅承担 NLP Agent 自身的固定查询职责（差评抽样、情感落库等），不做安全校验，
  调用者必须传入受控 SQL。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

# 复用 sql_agent 中已有的环境变量解析与值序列化函数
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SQL_AGENT_DIR = _PROJECT_ROOT / "agents" / "sql_agent"
if str(_SQL_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_SQL_AGENT_DIR))

# 自动加载项目根目录的 .env（若存在；若已加载过则无副作用）
try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")
except Exception:
    # 没装 python-dotenv 或 .env 不存在时，静默跳过；
    # 由 _db_config_from_env() 在缺变量时显式报错
    pass

from tools.execute_sql import _db_config_from_env, _json_safe_value  # noqa: E402


def query(sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
    """执行只读 SELECT，返回反序列化后的 list[dict]。"""
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


def execute(sql: str, params: tuple | None = None) -> int:
    """执行写入语句（INSERT / UPDATE / DDL），返回受影响行数。

    P1 阶段把情感分数落库 `review_sentiment` 时会用到；当前 P0 暂未使用。
    """
    cfg = _db_config_from_env()
    cfg.setdefault("cursorclass", DictCursor)
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            affected = cur.execute(sql, params or ())
        conn.commit()
    finally:
        conn.close()
    return int(affected)
