"""创建 Agent 运行时使用的 MySQL 只读账号。

账号创建需要一个已有建用户/授权权限的维护账号。维护账号从
``AGENTIC_BI_DB_ADMIN_USER/PASSWORD`` 读取，未设置时兼容回退到
``AGENTIC_BI_DB_USER/PASSWORD``。该脚本只负责数据库账号与授权，不修改应用配置。

示例：
    python utils/create_readonly_user.py --host-pattern 10.0.0.12
    python utils/create_readonly_user.py --host-pattern '%'

``%`` 仅适合临时验证；部署时应替换为 Dashboard/Agent 所在主机的实际来源地址。
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import string
import sys
from pathlib import Path

import pymysql

ROOT_DIR = Path(__file__).resolve().parent.parent
LEGACY_DIR = ROOT_DIR / "legacy"
if str(LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_DIR))

from db_env import load_dotenv


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def _account_part(value: str, *, name: str, allow_percent: bool = False) -> str:
    pattern = r"^[A-Za-z0-9._:%-]+$" if allow_percent else _IDENTIFIER_RE
    if not value or not re.fullmatch(pattern, value):
        suffix = "、百分号" if allow_percent else ""
        raise ValueError(f"{name} 只允许字母、数字、点、下划线、冒号、连字符{suffix}")
    return value


def _quote_account(user: str, host: str) -> str:
    # user/host 已做白名单校验；这里生成 MySQL account name，不把输入直接当 SQL 片段。
    return "'{}'@'{}'".format(user, host)


def _load_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建 Agentic BI MySQL 只读账号")
    parser.add_argument(
        "--user",
        default=os.environ.get("AGENTIC_BI_DB_READONLY_USER", "agentic_bi_ro"),
        help="只读账号名（默认 AGENTIC_BI_DB_READONLY_USER 或 agentic_bi_ro）",
    )
    parser.add_argument(
        "--host-pattern",
        default=os.environ.get("AGENTIC_BI_DB_READONLY_HOST", "localhost"),
        help="MySQL 账号 host 匹配范围；生产环境请填应用实际来源地址",
    )
    parser.add_argument(
        "--password",
        help="只读账号密码；省略时读取 AGENTIC_BI_DB_READONLY_PASSWORD 或交互输入",
    )
    parser.add_argument(
        "--generate-password",
        action="store_true",
        help="生成随机密码并打印一次（适合首次创建后写入本地密钥管理）",
    )
    return parser.parse_args()


def _password(args: argparse.Namespace) -> str:
    value = args.password or os.environ.get("AGENTIC_BI_DB_READONLY_PASSWORD")
    if value:
        return value
    if args.generate_password:
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
        value = "".join(secrets.choice(alphabet) for _ in range(32))
        print(f"生成的只读密码（仅显示一次）：{value}")
        return value
    value = getpass.getpass("只读账号密码：")
    if not value:
        raise ValueError("只读账号密码不能为空")
    return value


def main() -> int:
    load_dotenv()
    args = _load_args()
    user = _account_part(args.user, name="--user")
    host = _account_part(args.host_pattern, name="--host-pattern", allow_percent=True)
    password = _password(args)

    admin_user = os.environ.get("AGENTIC_BI_DB_ADMIN_USER") or os.environ.get(
        "AGENTIC_BI_DB_USER"
    )
    admin_password = os.environ.get("AGENTIC_BI_DB_ADMIN_PASSWORD") or os.environ.get(
        "AGENTIC_BI_DB_PASSWORD"
    )
    required = {
        "AGENTIC_BI_DB_HOST": os.environ.get("AGENTIC_BI_DB_HOST"),
        "AGENTIC_BI_DB_PORT": os.environ.get("AGENTIC_BI_DB_PORT"),
        "AGENTIC_BI_DB_NAME": os.environ.get("AGENTIC_BI_DB_NAME"),
        "AGENTIC_BI_DB_ADMIN_USER 或 AGENTIC_BI_DB_USER": admin_user,
        "AGENTIC_BI_DB_ADMIN_PASSWORD 或 AGENTIC_BI_DB_PASSWORD": admin_password,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise SystemExit("缺少数据库维护配置：" + ", ".join(missing))

    database = _account_part(os.environ["AGENTIC_BI_DB_NAME"], name="AGENTIC_BI_DB_NAME")
    port = int(os.environ["AGENTIC_BI_DB_PORT"])
    account = _quote_account(user, host)
    db_sql = f"`{database.replace('`', '``')}`"

    try:
        connection = pymysql.connect(
            host=os.environ["AGENTIC_BI_DB_HOST"],
            port=port,
            user=admin_user,
            password=admin_password,
            charset="utf8mb4",
            autocommit=True,
        )
    except pymysql.MySQLError as exc:
        raise SystemExit(f"无法连接 MySQL：{exc}") from exc
    try:
        try:
            with connection.cursor() as cursor:
                # account 中可能包含 MySQL host 通配符 ``%``；避免把它当成 PyMySQL
                # 参数化字符串的格式占位符。密码由驱动负责 SQL 字面量转义。
                password_sql = connection.escape(password)
                cursor.execute(
                    f"CREATE USER IF NOT EXISTS {account} IDENTIFIED BY {password_sql}"
                )
                # IF NOT EXISTS 不会改已有密码；再 ALTER 一次保证与 .env 对齐
                cursor.execute(f"ALTER USER {account} IDENTIFIED BY {password_sql}")
                cursor.execute(f"GRANT SELECT, SHOW VIEW ON {db_sql}.* TO {account}")
                cursor.execute(f"SHOW GRANTS FOR {account}")
                grants = [row[0] for row in cursor.fetchall()]
        except pymysql.MySQLError as exc:
            if getattr(exc, "args", [None])[0] == 1227:
                print(
                    "维护账号缺少 CREATE USER/GRANT OPTION。"
                    "请设置 AGENTIC_BI_DB_ADMIN_USER/PASSWORD 后重跑，或让管理员执行：",
                    file=sys.stderr,
                )
                if "password_sql" in locals():
                    print(
                        f"CREATE USER IF NOT EXISTS {account} IDENTIFIED BY {password_sql};",
                        file=sys.stderr,
                    )
                    print(
                        f"ALTER USER {account} IDENTIFIED BY {password_sql};",
                        file=sys.stderr,
                    )
                    print(
                        f"GRANT SELECT, SHOW VIEW ON {db_sql}.* TO {account};",
                        file=sys.stderr,
                    )
                raise SystemExit(1) from exc
            raise SystemExit(f"创建或授权只读账号失败：{exc}") from exc
    finally:
        connection.close()

    print(f"只读账号已就绪：{account}")
    print(f"授权数据库：{database}")
    for grant in grants:
        print(grant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
