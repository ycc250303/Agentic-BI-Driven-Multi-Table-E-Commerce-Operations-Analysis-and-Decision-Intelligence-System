#!/usr/bin/env python3
"""
预聚合视图刷新脚本

功能：
1. 连接数据库并读取视图创建SQL文件
2. 按语句执行DROP VIEW和CREATE VIEW
3. 验证每个视图创建成功并显示记录数
4. 输出详细的执行日志

使用方法：
    设置 AGENTIC_BI_DB_* 环境变量（见项目 README）后执行：
    python refresh_views.py
"""

import mysql.connector
from pathlib import Path
from typing import Dict, List

from db_env import mysql_connector_config

# 项目路径
ROOT_DIR = Path(__file__).resolve().parent.parent
SQL_FILE = ROOT_DIR / "utils" / "create_materialized_views.sql"


def parse_sql_file(sql_file: Path) -> List[str]:
    """
    解析SQL文件，提取独立的SQL语句

    Args:
        sql_file: SQL文件路径

    Returns:
        SQL语句列表
    """
    sql_text = sql_file.read_text(encoding="utf-8")

    # 移除SQL注释
    lines = []
    for line in sql_text.split("\n"):
        # 跳过注释行
        if line.strip().startswith("--"):
            continue
        lines.append(line)

    sql_text = "\n".join(lines)

    # 按分号分割语句
    statements = []
    for stmt in sql_text.split(";"):
        stmt = stmt.strip()
        if stmt:
            statements.append(stmt)

    return statements


def execute_view_refresh(connection, sql_statements: List[str]) -> Dict[str, bool]:
    """
    执行视图刷新SQL语句

    Args:
        connection: 数据库连接对象
        sql_statements: SQL语句列表

    Returns:
        视图名称到执行结果的映射
    """
    results = {}

    with connection.cursor() as cursor:
        for stmt in sql_statements:
            # 跳过空语句和纯注释
            if not stmt.strip():
                continue

            try:
                # 提取视图名称（从CREATE VIEW或DROP VIEW语句中）
                view_name = None
                stmt_upper = stmt.upper()

                if "CREATE VIEW" in stmt_upper:
                    # CREATE VIEW view_name AS ...
                    start = stmt_upper.index("CREATE VIEW") + len("CREATE VIEW")
                    end = stmt_upper.index(" AS", start)
                    view_name = stmt[start:end].strip()
                elif "DROP VIEW" in stmt_upper:
                    # DROP VIEW IF EXISTS view_name
                    start = stmt_upper.index("DROP VIEW") + len("DROP VIEW")
                    remainder = stmt[start:].strip()
                    if remainder.upper().startswith("IF EXISTS"):
                        remainder = remainder[len("IF EXISTS"):].strip()
                    view_name = remainder.strip()

                # 执行SQL
                cursor.execute(stmt)
                connection.commit()

                if view_name:
                    results[view_name] = True
                    print(f"[SUCCESS] {view_name}")

            except Exception as e:
                if view_name:
                    results[view_name] = False
                    print(f"[FAILED] {view_name}: {str(e)}")
                else:
                    print(f"[WARNING] Failed to execute statement: {str(e)}")

    return results


def verify_views(connection) -> Dict[str, int]:
    """
    验证视图创建成功并返回每个视图的记录数

    Args:
        connection: 数据库连接对象

    Returns:
        视图名称到记录数的映射
    """
    view_counts = {}

    # 所有预定义的视图名称
    view_names = [
        "mv_monthly_sales",
        "mv_state_sales",
        "mv_category_sales",
        "mv_delivery_perf",
        "mv_seller_perf",
        "mv_payment_dist",
    ]

    with connection.cursor() as cursor:
        for view_name in view_names:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {view_name}")
                count = cursor.fetchone()[0]
                view_counts[view_name] = count
            except Exception as e:
                view_counts[view_name] = -1  # -1表示视图不存在或查询失败
                print(f"[ERROR] Failed to query view {view_name}: {str(e)}")

    return view_counts


def main():
    """主函数"""
    print("=" * 60)
    print("预聚合视图刷新脚本")
    print("=" * 60)
    print()

    # 检查SQL文件是否存在
    if not SQL_FILE.exists():
        print(f"[ERROR] SQL文件不存在: {SQL_FILE}")
        return

    print(f"[INFO] 读取SQL文件: {SQL_FILE}")

    # 解析SQL文件
    try:
        sql_statements = parse_sql_file(SQL_FILE)
        print(f"[INFO] 解析到 {len(sql_statements)} 条SQL语句")
    except Exception as e:
        print(f"[ERROR] 解析SQL文件失败: {str(e)}")
        return

    # 连接数据库
    print()
    try:
        db_cfg = mysql_connector_config(autocommit=False)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return

    print(f"[INFO] 连接数据库: {db_cfg['host']}:{db_cfg['port']}/{db_cfg['database']}")

    try:
        connection = mysql.connector.connect(**db_cfg)
        print("[SUCCESS] 数据库连接成功")
    except Exception as e:
        print(f"[ERROR] 数据库连接失败: {str(e)}")
        return

    # 执行视图刷新
    print()
    print("[START] 开始创建/刷新视图...")
    print("-" * 60)

    results = execute_view_refresh(connection, sql_statements)

    print("-" * 60)

    # 统计结果
    success_count = sum(1 for v in results.values() if v)
    failed_count = len(results) - success_count

    print()
    print(f"[SUMMARY] 执行完成: 成功 {success_count} 个, 失败 {failed_count} 个")
    print()

    # 验证视图
    print("[VERIFY] 验证视图创建结果...")
    print("-" * 60)

    view_counts = verify_views(connection)

    print(f"{'视图名称':<30} {'记录数':>15}")
    print("-" * 60)

    for view_name, count in view_counts.items():
        if count >= 0:
            print(f"{view_name:<30} {count:>15,}")
        else:
            print(f"{view_name:<30} {'FAILED':>15}")

    print("-" * 60)
    print()

    # 显示所有现有视图
    print("[INFO] 数据库中所有视图列表:")
    with connection.cursor() as cursor:
        cursor.execute("SHOW FULL TABLES WHERE TABLE_TYPE LIKE 'VIEW'")
        views = cursor.fetchall()
        if views:
            for view in views:
                print(f"  - {view[0]}")
        else:
            print("  (无视图)")

    # 关闭连接
    connection.close()
    print()
    print("[DONE] 脚本执行完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
