#!/usr/bin/env python3
"""
创建并切换到目标数据库。

功能：
1. 读取与项目一致的数据库环境变量
2. 连接到 MySQL 服务端（不预先指定 database）
3. 创建目标数据库（如果不存在）
4. 执行 USE <database> 切换到目标数据库

用法：
    python utils/init_database.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pymysql

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import db_env  # noqa: F401  # 触发 .env 自动加载


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"[ERROR] 缺少环境变量: {name}")
    return value


def _env_port(name: str) -> int:
    raw = _env(name)
    try:
        return int(raw)
    except ValueError as e:
        raise SystemExit(f"[ERROR] {name} 必须是整数") from e


def _quote_identifier(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def main() -> None:
    host = _env("AGENTIC_BI_DB_HOST")
    port = _env_port("AGENTIC_BI_DB_PORT")
    user = _env("AGENTIC_BI_DB_USER")
    password = _env("AGENTIC_BI_DB_PASSWORD")
    database = _env("AGENTIC_BI_DB_NAME")

    print("[INFO] 连接 MySQL 服务端...")
    connection = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        charset="utf8mb4",
        autocommit=True,
    )

    db_sql = _quote_identifier(database)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS {db_sql} "
                "DEFAULT CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_0900_ai_ci"
            )
            print(f"[SUCCESS] 数据库已创建或已存在: {database}")

            cursor.execute(f"USE {db_sql}")
            cursor.execute("SELECT DATABASE()")
            current_db = cursor.fetchone()[0]
            print(f"[SUCCESS] 当前已切换到数据库: {current_db}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
