#!/usr/bin/env python3
"""
预聚合视图 vs 原始表聚合 查询耗时对比。

- 多组场景：与 utils/create_materialized_views.sql 中各视图一一对应。
- 每组对比：
  - raw_join：与视图定义等价的多表 JOIN + GROUP BY（规范写法）
  - raw_correlated（可选）：按订单做相关子查询后再聚合，放大与预聚合层的耗时差异
  - view：SELECT * FROM mv_*

用法：
  python utils/benchmark_preagg_vs_raw.py
  python utils/benchmark_preagg_vs_raw.py --warmup 1 --runs 5 --out docs/figures/preagg_benchmark.png
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import mysql.connector

ROOT_DIR = Path(__file__).resolve().parent.parent


def _db_config_from_env() -> dict:
    return {
        "host": os.getenv("AGENTIC_BI_DB_HOST", "111.229.81.45"),
        "port": int(os.getenv("AGENTIC_BI_DB_PORT", "3306")),
        "user": os.getenv("AGENTIC_BI_DB_USER", "agentic_bi"),
        "password": os.getenv("AGENTIC_BI_DB_PASSWORD", "agentic_bi"),
        "database": os.getenv("AGENTIC_BI_DB_NAME", "agentic_bi"),
        "charset": "utf8mb4",
        "autocommit": True,
    }


ORDER_STATUS_IN = "('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')"

# 与 create_materialized_views.sql 中视图定义一致（规范 JOIN 聚合）
SQL_RAW: Dict[str, str] = {
    "mv_monthly_sales": f"""
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    SUM(oi.price + oi.freight_value) AS total_gmv,
    COUNT(DISTINCT o.order_id) AS total_orders,
    SUM(oi.price + oi.freight_value) / COUNT(DISTINCT o.order_id) AS avg_basket,
    SUM(oi.freight_value) AS total_freight
FROM orders o
INNER JOIN order_items oi ON o.order_id = oi.order_id
WHERE o.order_status IN {ORDER_STATUS_IN}
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')
""",
    "mv_state_sales": f"""
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    c.customer_state,
    SUM(oi.price + oi.freight_value) AS total_gmv,
    COUNT(DISTINCT o.order_id) AS total_orders,
    COUNT(DISTINCT c.customer_unique_id) AS unique_customers
FROM orders o
INNER JOIN order_items oi ON o.order_id = oi.order_id
INNER JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status IN {ORDER_STATUS_IN}
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'), c.customer_state
""",
    "mv_category_sales": f"""
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    COALESCE(pct.product_category_name_english, p.product_category_name) AS product_category_english,
    SUM(oi.price) AS total_gmv,
    COUNT(DISTINCT oi.order_id) AS total_orders,
    AVG(oi.price) AS avg_price
FROM orders o
INNER JOIN order_items oi ON o.order_id = oi.order_id
INNER JOIN products p ON oi.product_id = p.product_id
LEFT JOIN product_category_name_translation pct ON p.product_category_name = pct.product_category_name
WHERE o.order_status IN {ORDER_STATUS_IN}
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'),
    COALESCE(pct.product_category_name_english, p.product_category_name)
""",
    "mv_delivery_perf": """
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    c.customer_state,
    AVG(DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp)) AS avg_delivery_days,
    SUM(CASE WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS on_time_rate,
    SUM(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1 ELSE 0 END) AS delayed_orders
FROM orders o
INNER JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'), c.customer_state
""",
    "mv_seller_perf": f"""
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    s.seller_id,
    s.seller_state,
    SUM(oi.price + oi.freight_value) AS total_gmv,
    COUNT(DISTINCT oi.order_id) AS total_orders,
    AVG(r.review_score) AS avg_review_score
FROM orders o
INNER JOIN order_items oi ON o.order_id = oi.order_id
INNER JOIN sellers s ON oi.seller_id = s.seller_id
LEFT JOIN order_reviews r ON o.order_id = r.order_id
WHERE o.order_status IN {ORDER_STATUS_IN}
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'), s.seller_id, s.seller_state
""",
    "mv_payment_dist": f"""
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
    p.payment_type,
    COUNT(DISTINCT p.order_id) AS total_transactions,
    AVG(p.payment_installments) AS avg_installments,
    SUM(p.payment_value) AS total_value
FROM orders o
INNER JOIN payments p ON o.order_id = p.order_id
WHERE o.order_status IN {ORDER_STATUS_IN}
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'), p.payment_type
""",
}

SQL_RAW_CORRELATED: Dict[str, Optional[str]] = {
    "mv_monthly_sales": """
SELECT
    inner_q.ym,
    SUM(inner_q.order_gmv) AS total_gmv,
    COUNT(DISTINCT inner_q.order_id) AS total_orders,
    SUM(inner_q.order_gmv) / COUNT(DISTINCT inner_q.order_id) AS avg_basket,
    SUM(inner_q.order_freight) AS total_freight
FROM (
    SELECT
        DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS ym,
        o.order_id,
        (SELECT SUM(oi.price + oi.freight_value) FROM order_items oi WHERE oi.order_id = o.order_id) AS order_gmv,
        (SELECT SUM(oi.freight_value) FROM order_items oi WHERE oi.order_id = o.order_id) AS order_freight
    FROM orders o
    WHERE o.order_status IN ('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')
) AS inner_q
GROUP BY inner_q.ym
""",
    "mv_state_sales": """
SELECT
    inner_q.ym,
    inner_q.customer_state,
    SUM(inner_q.order_gmv) AS total_gmv,
    COUNT(DISTINCT inner_q.order_id) AS total_orders,
    COUNT(DISTINCT inner_q.customer_unique_id) AS unique_customers
FROM (
    SELECT
        DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS ym,
        c.customer_state,
        o.order_id,
        c.customer_unique_id,
        (SELECT SUM(oi.price + oi.freight_value) FROM order_items oi WHERE oi.order_id = o.order_id) AS order_gmv
    FROM orders o
    INNER JOIN customers c ON o.customer_id = c.customer_id
    WHERE o.order_status IN ('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')
) AS inner_q
GROUP BY inner_q.ym, inner_q.customer_state
""",
    "mv_category_sales": """
SELECT
    inner_q.ym,
    inner_q.product_category_english,
    SUM(inner_q.cat_gmv) AS total_gmv,
    COUNT(DISTINCT inner_q.order_id) AS total_orders,
    SUM(inner_q.cat_gmv) / NULLIF(SUM(inner_q.cat_lines), 0) AS avg_price
FROM (
    SELECT DISTINCT
        DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS ym,
        COALESCE(pct.product_category_name_english, p.product_category_name) AS product_category_english,
        o.order_id,
        (
            SELECT COALESCE(SUM(oi2.price), 0)
            FROM order_items oi2
            INNER JOIN products p2 ON oi2.product_id = p2.product_id
            LEFT JOIN product_category_name_translation pct2 ON p2.product_category_name = pct2.product_category_name
            WHERE oi2.order_id = o.order_id
              AND COALESCE(pct2.product_category_name_english, p2.product_category_name)
                  = COALESCE(pct.product_category_name_english, p.product_category_name)
        ) AS cat_gmv,
        (
            SELECT COUNT(*)
            FROM order_items oi2
            INNER JOIN products p2 ON oi2.product_id = p2.product_id
            LEFT JOIN product_category_name_translation pct2 ON p2.product_category_name = pct2.product_category_name
            WHERE oi2.order_id = o.order_id
              AND COALESCE(pct2.product_category_name_english, p2.product_category_name)
                  = COALESCE(pct.product_category_name_english, p.product_category_name)
        ) AS cat_lines
    FROM orders o
    INNER JOIN order_items oi ON o.order_id = oi.order_id
    INNER JOIN products p ON oi.product_id = p.product_id
    LEFT JOIN product_category_name_translation pct ON p.product_category_name = pct.product_category_name
    WHERE o.order_status IN ('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')
) AS inner_q
GROUP BY inner_q.ym, inner_q.product_category_english
""",
    "mv_delivery_perf": """
SELECT
    inner_q.ym,
    inner_q.customer_state,
    AVG(inner_q.delivery_days) AS avg_delivery_days,
    SUM(inner_q.ontime_flag) * 1.0 / COUNT(*) AS on_time_rate,
    SUM(inner_q.delay_flag) AS delayed_orders
FROM (
    SELECT
        DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS ym,
        c.customer_state,
        DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp) AS delivery_days,
        CASE WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date THEN 1 ELSE 0 END AS ontime_flag,
        CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1 ELSE 0 END AS delay_flag
    FROM orders o
    INNER JOIN customers c ON o.customer_id = c.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
) AS inner_q
GROUP BY inner_q.ym, inner_q.customer_state
""",
    "mv_seller_perf": """
SELECT
    inner_q.ym,
    inner_q.seller_id,
    inner_q.seller_state,
    SUM(inner_q.order_gmv) AS total_gmv,
    COUNT(DISTINCT inner_q.order_id) AS total_orders,
    AVG(inner_q.review_score) AS avg_review_score
FROM (
    SELECT DISTINCT
        DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS ym,
        s.seller_id,
        s.seller_state,
        o.order_id,
        (
            SELECT SUM(oi.price + oi.freight_value)
            FROM order_items oi
            WHERE oi.order_id = o.order_id AND oi.seller_id = s.seller_id
        ) AS order_gmv,
        (SELECT AVG(r2.review_score) FROM order_reviews r2 WHERE r2.order_id = o.order_id) AS review_score
    FROM orders o
    INNER JOIN order_items oi0 ON o.order_id = oi0.order_id
    INNER JOIN sellers s ON oi0.seller_id = s.seller_id
    WHERE o.order_status IN ('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')
) AS inner_q
GROUP BY inner_q.ym, inner_q.seller_id, inner_q.seller_state
""",
    "mv_payment_dist": """
SELECT
    inner_q.ym,
    inner_q.payment_type,
    COUNT(DISTINCT inner_q.order_id) AS total_transactions,
    AVG(inner_q.installments) AS avg_installments,
    SUM(inner_q.pay_val) AS total_value
FROM (
    SELECT
        DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS ym,
        p.payment_type,
        p.order_id,
        p.payment_installments AS installments,
        (SELECT SUM(p2.payment_value) FROM payments p2 WHERE p2.order_id = p.order_id AND p2.payment_type = p.payment_type) AS pay_val
    FROM orders o
    INNER JOIN payments p ON o.order_id = p.order_id
    WHERE o.order_status IN ('delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced')
) AS inner_q
GROUP BY inner_q.ym, inner_q.payment_type
""",
}


@dataclass
class TimingResult:
    label: str
    seconds: List[float] = field(default_factory=list)

    @property
    def mean_ms(self) -> float:
        return statistics.mean(self.seconds) * 1000 if self.seconds else 0.0


def _run_query(conn, sql: str) -> float:
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.fetchall()
    return time.perf_counter() - t0


def benchmark_label(conn, sql: str, warmup: int, runs: int) -> TimingResult:
    w = TimingResult("tmp")
    for _ in range(warmup):
        _run_query(conn, sql)
    w.seconds = [_run_query(conn, sql) for _ in range(runs)]
    return w


def _plot(results: Dict[str, Dict[str, TimingResult]], out_path: Path) -> None:
    import matplotlib.pyplot as plt

    views = list(results.keys())
    modes_order = ["raw_join", "raw_correlated", "view"]
    modes = [m for m in modes_order if any(m in results[v] for v in views)]
    colors = {"raw_join": "#4e79a7", "raw_correlated": "#f28e2b", "view": "#59a14f"}
    # 使用英文标签，避免无中文字体的环境导出 PNG 时出现缺字方块（报告正文仍为中文说明）
    labels_plot = {
        "raw_join": "Raw tables · JOIN + GROUP BY",
        "raw_correlated": "Raw tables · correlated subqueries",
        "view": "Pre-aggregated VIEW",
    }

    x = range(len(views))
    n_modes = max(len(modes), 1)
    width = min(0.28, 0.9 / n_modes)
    fig, ax = plt.subplots(figsize=(12, 5))

    for i, mode in enumerate(modes):
        heights = []
        for v in views:
            tr = results[v].get(mode)
            heights.append(tr.mean_ms if tr and tr.seconds else 0.0)
        offset = (i - (len(modes) - 1) / 2) * width
        ax.bar([xi + offset for xi in x], heights, width, label=labels_plot[mode], color=colors[mode])

    ax.set_ylabel("Mean time (ms)")
    ax.set_title("Same analytics: raw aggregation vs SELECT from pre-aggregated VIEW")
    ax.set_xticks(list(x))
    ax.set_xticklabels([v.replace("mv_", "") for v in views], rotation=20, ha="right")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--warmup", type=int, default=1)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--out", type=Path, default=ROOT_DIR / "docs" / "figures" / "preagg_benchmark.png")
    p.add_argument("--json-out", type=Path, default=None, help="可选：导出原始计时 JSON")
    p.add_argument("--skip-correlated", action="store_true", help="跳过相关子查询用例（仅 JOIN vs 视图）")
    args = p.parse_args()

    cfg = _db_config_from_env()
    view_names = [
        "mv_monthly_sales",
        "mv_state_sales",
        "mv_category_sales",
        "mv_delivery_perf",
        "mv_seller_perf",
        "mv_payment_dist",
    ]

    print(f"[INFO] 连接 {cfg['host']}:{cfg['port']}/{cfg['database']}")
    try:
        conn = mysql.connector.connect(**cfg)
    except mysql.connector.Error as e:
        print(f"[ERROR] 连接失败: {e}", file=sys.stderr)
        return 1

    results: Dict[str, Dict[str, TimingResult]] = {}

    try:
        for vn in view_names:
            print(f"\n--- {vn} ---")
            bundle: Dict[str, TimingResult] = {}
            raw_sql = SQL_RAW[vn].strip()
            view_sql = f"SELECT * FROM `{vn.replace('`', '')}`"

            rj = benchmark_label(conn, raw_sql, args.warmup, args.runs)
            rj.label = "raw_join"
            bundle["raw_join"] = rj
            print(f"  raw_join       平均 {rj.mean_ms:,.1f} ms")

            if not args.skip_correlated and SQL_RAW_CORRELATED.get(vn):
                rc = benchmark_label(conn, SQL_RAW_CORRELATED[vn].strip(), args.warmup, args.runs)
                rc.label = "raw_correlated"
                bundle["raw_correlated"] = rc
                print(f"  raw_correlated 平均 {rc.mean_ms:,.1f} ms")

            rv = benchmark_label(conn, view_sql, args.warmup, args.runs)
            rv.label = "view"
            bundle["view"] = rv
            print(f"  view           平均 {rv.mean_ms:,.1f} ms")

            results[vn] = bundle
    finally:
        conn.close()

    export: Dict[str, Dict[str, float]] = {}
    for vn, bundle in results.items():
        export[vn] = {k: v.mean_ms for k, v in bundle.items()}
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(export, indent=2), encoding="utf-8")

    try:
        _plot(results, args.out)
        print(f"\n[OK] 图表已保存: {args.out.resolve()}")
    except ImportError:
        print("[WARN] 未安装 matplotlib，跳过作图。pip install matplotlib", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
