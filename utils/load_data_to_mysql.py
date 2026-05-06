#!/usr/bin/env python3
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

import pymysql

from db_env import pymysql_config

# 项目路径与输入文件位置
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
SCHEMA_SQL = ROOT_DIR / "utils" / "origin_table.sql"

BATCH_SIZE = 5000


# 以下转换函数用于把 CSV 字符串转换为数据库字段类型
# required: 空值时给默认值，避免 NOT NULL 字段插入失败
# nullable: 空值时写入 NULL
def to_str_required(value: str) -> str:
    return (value or "").strip()


def to_str_nullable(value: str):
    val = (value or "").strip()
    return val if val else None


def to_int_required(value: str) -> int:
    val = (value or "").strip()
    return int(val) if val else 0


def to_int_nullable(value: str):
    val = (value or "").strip()
    return int(val) if val else None


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
    # 每项定义: 目标表、对应 CSV、字段顺序、字段转换函数
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


def execute_schema_sql(cursor) -> None:
    # 简单按 ";" 切分并执行建表脚本
    sql_text = SCHEMA_SQL.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]
    for statement in statements:
        cursor.execute(statement)


def insert_batch_ignore_duplicates(cursor, connection, insert_sql: str, batch: list[tuple]) -> tuple[int, int]:
    """
    使用 INSERT IGNORE 批量插入，主键重复时自动跳过。
    返回值: (成功插入行数, 重复行数)
    """
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
    # IGNORE: 遇到重复主键(如重复 id)时直接跳过
    insert_sql = f"INSERT IGNORE INTO {table_name} ({col_sql}) VALUES ({placeholders})"

    print(f"[START] 导入表 {table_name} <- {csv_file.name}")

    with connection.cursor() as cursor:
        with csv_file.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            batch = []
            row_count = 0
            duplicate_count = 0

            for row in reader:
                values = []
                for col, convert in zip(columns, converters):
                    raw = row.get(col, "")
                    values.append(convert(raw))
                batch.append(tuple(values))

                # 按批次入库，减少单次事务体积并提升导入效率
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


def main() -> None:
    print("连接数据库并执行建表脚本...")
    try:
        db_cfg = pymysql_config(autocommit=False)
    except ValueError as e:
        raise SystemExit(f"[ERROR] {e}") from e
    connection = pymysql.connect(**db_cfg)
    try:
        with connection.cursor() as cursor:
            execute_schema_sql(cursor)
        connection.commit()
        print("建表完成，开始导入 CSV 数据...")

        for table_conf in TABLE_CONFIG:
            load_single_table(connection, table_conf)

        print("全部表导入完成。")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
