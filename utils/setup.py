#!/usr/bin/env python3
"""数据库初始化入口：建库、原始表+CSV、预聚合视图、NLP 表、翻译表补导。

用法（仓库根目录）：
    python utils/setup.py              # init + load + views
    python utils/setup.py init         # 仅 CREATE DATABASE
    python utils/setup.py load         # DROP/CREATE 9 张原始表并导入 CSV（不动 NLP 表）
    python utils/setup.py views        # 刷新 6 个 mv_* 视图
    python utils/setup.py nlp-tables   # DROP/CREATE 情感与主题表（会清空已灌 NLP 数据）
    python utils/setup.py translation  # 只重建 product_category_name_translation（71 行）
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

import pymysql

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db_env import pymysql_config

DATA_DIR = ROOT_DIR / "data"
SCHEMA_SQL = ROOT_DIR / "utils" / "schema.sql"
BATCH_SIZE = 5000
TRANSLATION_EXPECTED = 71
VIEW_NAMES = (
    "mv_monthly_sales",
    "mv_state_sales",
    "mv_category_sales",
    "mv_delivery_perf",
    "mv_seller_perf",
    "mv_payment_dist",
)


def to_str_required(value: str) -> str:
    return (value or "").strip()


def to_int_required(value: str) -> int:
    val = (value or "").strip()
    return int(val) if val else 0


def to_decimal_required(value: str) -> Decimal:
    val = (value or "").strip()
    if not val:
        return Decimal("0")
    try:
        return Decimal(val)
    except InvalidOperation:
        return Decimal("0")


def to_decimal_nullable(value: str):
    val = (value or "").strip()
    if not val:
        return None
    try:
        return Decimal(val)
    except InvalidOperation:
        return None


def to_datetime_nullable(value: str):
    val = (value or "").strip()
    return val if val else None


def to_datetime_required(value: str) -> str:
    val = (value or "").strip()
    return val if val else "1970-01-01 00:00:00"


TABLE_CONFIG = [
    {
        "table": "orders",
        "csv": "olist_orders_dataset.csv",
        "columns": [
            "order_id",
            "customer_id",
            "order_status",
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
        "converters": [
            to_str_required,
            to_str_required,
            to_str_required,
            to_datetime_nullable,
            to_datetime_nullable,
            to_datetime_nullable,
            to_datetime_nullable,
            to_datetime_nullable,
        ],
    },
    {
        "table": "order_items",
        "csv": "olist_order_items_dataset.csv",
        "columns": [
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "shipping_limit_date",
            "price",
            "freight_value",
        ],
        "converters": [
            to_str_required,
            to_int_required,
            to_str_required,
            to_str_required,
            to_datetime_nullable,
            to_decimal_nullable,
            to_decimal_nullable,
        ],
    },
    {
        "table": "products",
        "csv": "olist_products_dataset.csv",
        "columns": [
            "product_id",
            "product_category_name",
            "product_name_lenght",
            "product_description_lenght",
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ],
        "converters": [
            to_str_required,
            to_str_required,
            to_int_required,
            to_int_required,
            to_int_required,
            to_int_required,
            to_int_required,
            to_int_required,
            to_int_required,
        ],
    },
    {
        "table": "customers",
        "csv": "olist_customers_dataset.csv",
        "columns": [
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ],
        "converters": [
            to_str_required,
            to_str_required,
            to_int_required,
            to_str_required,
            to_str_required,
        ],
    },
    {
        "table": "sellers",
        "csv": "olist_sellers_dataset.csv",
        "columns": [
            "seller_id",
            "seller_zip_code_prefix",
            "seller_city",
            "seller_state",
        ],
        "converters": [
            to_str_required,
            to_int_required,
            to_str_required,
            to_str_required,
        ],
    },
    {
        "table": "payments",
        "csv": "olist_order_payments_dataset.csv",
        "columns": [
            "order_id",
            "payment_sequential",
            "payment_type",
            "payment_installments",
            "payment_value",
        ],
        "converters": [
            to_str_required,
            to_int_required,
            to_str_required,
            to_int_required,
            to_decimal_required,
        ],
    },
    {
        "table": "order_reviews",
        "csv": "olist_order_reviews_dataset.csv",
        "columns": [
            "review_id",
            "order_id",
            "review_score",
            "review_comment_title",
            "review_comment_message",
            "review_creation_date",
            "review_answer_timestamp",
        ],
        "converters": [
            to_str_required,
            to_str_required,
            to_int_required,
            to_str_required,
            to_str_required,
            to_datetime_required,
            to_datetime_required,
        ],
    },
    {
        "table": "geolocation",
        "csv": "olist_geolocation_dataset.csv",
        "columns": [
            "geolocation_zip_code_prefix",
            "geolocation_lat",
            "geolocation_lng",
            "geolocation_city",
            "geolocation_state",
        ],
        "converters": [
            to_int_required,
            to_decimal_required,
            to_decimal_required,
            to_str_required,
            to_str_required,
        ],
    },
    {
        "table": "product_category_name_translation",
        "csv": "product_category_name_translation.csv",
        "columns": [
            "product_category_name",
            "product_category_name_english",
        ],
        "converters": [
            to_str_required,
            to_str_required,
        ],
    },
]


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"[ERROR] 缺少环境变量: {name}")
    return value


def schema_section(name: str) -> str:
    text = SCHEMA_SQL.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^-- @section (\w+)\s*$", text)
    sections: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        sections[parts[i]] = parts[i + 1]
    if name not in sections:
        raise SystemExit(f"[ERROR] {SCHEMA_SQL.name} 缺少 -- @section {name}")
    return sections[name]


def sql_statements(sql_text: str) -> list[str]:
    kept: list[str] = []
    for line in sql_text.splitlines():
        if line.strip().startswith("--"):
            continue
        kept.append(line)
    return [s.strip() for s in "\n".join(kept).split(";") if s.strip()]


def execute_statements(cursor, statements: list[str]) -> None:
    for statement in statements:
        cursor.execute(statement)


def cmd_init() -> None:
    import db_env  # noqa: F401  # 触发 .env

    host = _env("AGENTIC_BI_DB_HOST")
    try:
        port = int(_env("AGENTIC_BI_DB_PORT"))
    except ValueError as e:
        raise SystemExit("[ERROR] AGENTIC_BI_DB_PORT 必须是整数") from e
    user = _env("AGENTIC_BI_DB_USER")
    password = _env("AGENTIC_BI_DB_PASSWORD")
    database = _env("AGENTIC_BI_DB_NAME")
    db_sql = "`" + database.replace("`", "``") + "`"

    print("[INFO] 连接 MySQL 服务端...")
    connection = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS {db_sql} "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
            cursor.execute(f"USE {db_sql}")
            cursor.execute("SELECT DATABASE()")
            print(f"[SUCCESS] 当前数据库: {cursor.fetchone()[0]}")
    finally:
        connection.close()


def insert_batch_ignore_duplicates(cursor, connection, insert_sql: str, batch: list[tuple]) -> tuple[int, int]:
    if not batch:
        return 0, 0
    cursor.executemany(insert_sql, batch)
    connection.commit()
    inserted = cursor.rowcount
    duplicates = len(batch) - inserted
    return inserted, duplicates


def load_single_table(connection, table_conf: dict) -> None:
    table_name = table_conf["table"]
    csv_file = DATA_DIR / table_conf["csv"]
    columns = table_conf["columns"]
    converters: list[Callable[[str], object]] = table_conf["converters"]
    placeholders = ", ".join(["%s"] * len(columns))
    col_sql = ", ".join(columns)
    insert_sql = f"INSERT IGNORE INTO {table_name} ({col_sql}) VALUES ({placeholders})"

    print(f"[START] 导入表 {table_name} <- {csv_file.name}")
    with connection.cursor() as cursor:
        with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            batch: list[tuple] = []
            row_count = 0
            duplicate_count = 0
            for row in reader:
                values = [convert(row.get(col, "") or "") for col, convert in zip(columns, converters)]
                batch.append(tuple(values))
                if len(batch) >= BATCH_SIZE:
                    inserted, duplicates = insert_batch_ignore_duplicates(cursor, connection, insert_sql, batch)
                    row_count += inserted
                    duplicate_count += duplicates
                    print(f"[PROGRESS] {table_name}: 已导入 {row_count} 行")
                    batch.clear()
            if batch:
                inserted, duplicates = insert_batch_ignore_duplicates(cursor, connection, insert_sql, batch)
                row_count += inserted
                duplicate_count += duplicates
    print(f"[DONE] 表 {table_name} 导入完成，共 {row_count} 行，重复 {duplicate_count} 行")


def cmd_load() -> None:
    print("连接数据库并执行原始表 DDL...")
    try:
        db_cfg = pymysql_config(autocommit=False)
    except ValueError as e:
        raise SystemExit(f"[ERROR] {e}") from e
    connection = pymysql.connect(**db_cfg)
    try:
        with connection.cursor() as cursor:
            execute_statements(cursor, sql_statements(schema_section("origin")))
        connection.commit()
        print("建表完成，开始导入 CSV...")
        for table_conf in TABLE_CONFIG:
            load_single_table(connection, table_conf)
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM product_category_name_translation")
            n = int(cursor.fetchone()[0])
        if n != TRANSLATION_EXPECTED:
            raise SystemExit(
                f"[ERROR] 翻译表行数={n}，期望 {TRANSLATION_EXPECTED}。"
                "CSV 须用 utf-8-sig 读取；勿对空主键 INSERT IGNORE。"
            )
        print("全部原始表导入完成。")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def cmd_views() -> None:
    try:
        db_cfg = pymysql_config(autocommit=False)
    except ValueError as e:
        raise SystemExit(f"[ERROR] {e}") from e
    statements = sql_statements(schema_section("views"))
    print(f"[INFO] 刷新预聚合视图，{len(statements)} 条 SQL")
    connection = pymysql.connect(**db_cfg)
    try:
        with connection.cursor() as cursor:
            execute_statements(cursor, statements)
            connection.commit()
            print(f"{'视图':<30} {'行数':>12}")
            for name in VIEW_NAMES:
                cursor.execute(f"SELECT COUNT(*) FROM `{name}`")
                print(f"{name:<30} {cursor.fetchone()[0]:>12,}")
            cursor.execute("SHOW FULL TABLES WHERE TABLE_TYPE LIKE 'VIEW'")
            print("[INFO] 库中视图:", ", ".join(row[0] for row in cursor.fetchall()) or "(无)")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def cmd_nlp_tables() -> None:
    try:
        db_cfg = pymysql_config(autocommit=False)
    except ValueError as e:
        raise SystemExit(f"[ERROR] {e}") from e
    print("[INFO] 重建 NLP 衍生表（会清空已有情感/主题数据）")
    connection = pymysql.connect(**db_cfg)
    try:
        with connection.cursor() as cursor:
            execute_statements(cursor, sql_statements(schema_section("nlp")))
        connection.commit()
        print("[SUCCESS] review_sentiment / review_topics / review_topic_meta 已重建")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _read_translation_rows() -> list[tuple[str, str]]:
    path = DATA_DIR / "product_category_name_translation.csv"
    rows: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        if "product_category_name" not in fieldnames:
            raise SystemExit(f"[ERROR] CSV 表头异常: {fieldnames!r}（应用 utf-8-sig 去掉 BOM）")
        for i, row in enumerate(reader, start=2):
            pt = (row.get("product_category_name") or "").strip()
            en = (row.get("product_category_name_english") or "").strip()
            if not pt or not en:
                raise SystemExit(f"[ERROR] {path.name}:{i} 存在空字段")
            rows.append((pt, en))
    if len(rows) != TRANSLATION_EXPECTED:
        raise SystemExit(f"[ERROR] CSV 记录数={len(rows)}，期望 {TRANSLATION_EXPECTED}")
    if len({pt for pt, _ in rows}) != len(rows):
        raise SystemExit("[ERROR] CSV 中 product_category_name 有重复")
    return rows


def cmd_translation() -> None:
    rows = _read_translation_rows()
    try:
        db_cfg = pymysql_config(autocommit=False)
    except ValueError as e:
        raise SystemExit(f"[ERROR] {e}") from e
    print(f"连接 {db_cfg['host']}:{db_cfg['port']}/{db_cfg['database']}，只重建翻译表")
    connection = pymysql.connect(**db_cfg)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM product_category_name_translation")
            print(f"[BEFORE] 行数 = {cursor.fetchone()[0]}")
            cursor.execute("DELETE FROM product_category_name_translation")
            cursor.executemany(
                "INSERT INTO product_category_name_translation "
                "(product_category_name, product_category_name_english) VALUES (%s, %s)",
                rows,
            )
            cursor.execute("SELECT COUNT(*) FROM product_category_name_translation")
            after = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM product_category_name_translation "
                "WHERE product_category_name = '' OR product_category_name IS NULL"
            )
            empty_pk = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT product_category_name, product_category_name_english "
                "FROM product_category_name_translation WHERE product_category_name = 'casa_conforto'"
            )
            casa = cursor.fetchone()
            if after != TRANSLATION_EXPECTED or empty_pk != 0:
                connection.rollback()
                raise SystemExit(f"[ERROR] 校验失败已回滚 count={after} empty_pk={empty_pk}")
            connection.commit()
            print(f"[AFTER] 行数 = {after}，空主键 = {empty_pk}，casa_conforto = {casa}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic BI 数据库初始化")
    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=("all", "init", "load", "views", "nlp-tables", "translation"),
        help="all=init+load+views（默认）",
    )
    args = parser.parse_args()
    if args.command == "init":
        cmd_init()
    elif args.command == "load":
        cmd_load()
    elif args.command == "views":
        cmd_views()
    elif args.command == "nlp-tables":
        cmd_nlp_tables()
    elif args.command == "translation":
        cmd_translation()
    else:
        cmd_init()
        cmd_load()
        cmd_views()


if __name__ == "__main__":
    main()
