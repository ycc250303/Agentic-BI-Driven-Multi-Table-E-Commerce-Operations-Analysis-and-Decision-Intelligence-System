"""从环境变量读取数据库连接参数，不设代码内默认值。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_ENV_KEYS = (
    "AGENTIC_BI_DB_HOST",
    "AGENTIC_BI_DB_PORT",
    "AGENTIC_BI_DB_USER",
    "AGENTIC_BI_DB_PASSWORD",
    "AGENTIC_BI_DB_NAME",
)


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
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


_load_dotenv()


def _base_mysql_params() -> dict[str, Any]:
    missing = [k for k in _ENV_KEYS if os.environ.get(k) in (None, "")]
    if missing:
        raise ValueError("缺少或未设置数据库环境变量：" + ", ".join(missing))
    try:
        port = int(os.environ["AGENTIC_BI_DB_PORT"])
    except ValueError as e:
        raise ValueError("AGENTIC_BI_DB_PORT 须为整数") from e
    return {
        "host": os.environ["AGENTIC_BI_DB_HOST"],
        "port": port,
        "user": os.environ["AGENTIC_BI_DB_USER"],
        "password": os.environ["AGENTIC_BI_DB_PASSWORD"],
        "database": os.environ["AGENTIC_BI_DB_NAME"],
    }


def pymysql_config(*, autocommit: bool = False) -> dict[str, Any]:
    cfg = _base_mysql_params()
    cfg["charset"] = "utf8mb4"
    cfg["autocommit"] = autocommit
    return cfg


def mysql_connector_config(*, autocommit: bool = True) -> dict[str, Any]:
    cfg = _base_mysql_params()
    cfg["charset"] = "utf8mb4"
    cfg["autocommit"] = autocommit
    return cfg
