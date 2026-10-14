"""旧版数据库配置入口，仅供 legacy Agent 与 ``utils`` 脚本使用。

运行时查询使用 ``readonly_*`` 配置，建库/灌库使用 ``writer_*`` 配置；
调用方不再直接拼接 ``AGENTIC_BI_DB_*`` 环境变量。新包的数据库配置在 data
纵切落地时进入 ``Settings``，不从这里读取。
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

_ENV_KEYS = (
    "AGENTIC_BI_DB_HOST",
    "AGENTIC_BI_DB_PORT",
    "AGENTIC_BI_DB_NAME",
)
_WRITER_ENV_KEYS = ("AGENTIC_BI_DB_USER", "AGENTIC_BI_DB_PASSWORD")
_READONLY_ENV_KEYS = (
    "AGENTIC_BI_DB_READONLY_USER",
    "AGENTIC_BI_DB_READONLY_PASSWORD",
)


def _repository_root() -> Path:
    """向上查找同时包含 ``pyproject.toml`` 与 ``src/`` 的仓库根。"""
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / "pyproject.toml").is_file() and (parent / "src").is_dir():
            return parent
    return here


def load_dotenv() -> None:
    """加载仓库根目录 ``.env``，不覆盖调用进程已显式设置的变量。"""
    env_path = _repository_root() / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value

load_dotenv()


def _base_mysql_params(*, readonly: bool = False) -> dict[str, Any]:
    credential_keys = _READONLY_ENV_KEYS if readonly else _WRITER_ENV_KEYS
    required = (*_ENV_KEYS, *credential_keys)
    missing = [k for k in required if os.environ.get(k) in (None, "")]
    if missing:
        raise ValueError("缺少或未设置数据库环境变量：" + ", ".join(missing))
    try:
        port = int(os.environ["AGENTIC_BI_DB_PORT"])
    except ValueError as e:
        raise ValueError("AGENTIC_BI_DB_PORT 须为整数") from e
    user_key, password_key = credential_keys
    return {
        "host": os.environ["AGENTIC_BI_DB_HOST"],
        "port": port,
        "user": os.environ[user_key],
        "password": os.environ[password_key],
        "database": os.environ["AGENTIC_BI_DB_NAME"],
    }


def pymysql_config(*, autocommit: bool = False, readonly: bool = False) -> dict[str, Any]:
    """返回 PyMySQL 配置；``readonly=True`` 强制使用独立只读账号。"""
    cfg = _base_mysql_params(readonly=readonly)
    cfg["charset"] = "utf8mb4"
    cfg["autocommit"] = autocommit
    return cfg


def readonly_pymysql_config(*, autocommit: bool = False) -> dict[str, Any]:
    """返回 Agent/在线查询专用的只读 PyMySQL 配置。"""
    return pymysql_config(autocommit=autocommit, readonly=True)


def writer_pymysql_config(*, autocommit: bool = False) -> dict[str, Any]:
    """返回建库、灌数和离线写入专用的 PyMySQL 配置。"""
    return pymysql_config(autocommit=autocommit, readonly=False)


def mysql_connector_config(
    *, autocommit: bool = True, readonly: bool = False
) -> dict[str, Any]:
    cfg = _base_mysql_params(readonly=readonly)
    cfg["charset"] = "utf8mb4"
    cfg["autocommit"] = autocommit
    return cfg


def readonly_mysql_connector_config(*, autocommit: bool = True) -> dict[str, Any]:
    """返回只读查询专用的 mysql-connector 配置。"""
    return mysql_connector_config(autocommit=autocommit, readonly=True)


def writer_mysql_connector_config(*, autocommit: bool = True) -> dict[str, Any]:
    """返回维护脚本专用的 mysql-connector 配置。"""
    return mysql_connector_config(autocommit=autocommit, readonly=False)


# 兼容旧脚本/外部调用；新代码应使用公开的 ``load_dotenv``。
_load_dotenv = load_dotenv


def json_safe_value(v: Any) -> Any:
    """把 MySQL 驱动常见类型转成 JSON 可序列化值；其余原样返回。"""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return v
