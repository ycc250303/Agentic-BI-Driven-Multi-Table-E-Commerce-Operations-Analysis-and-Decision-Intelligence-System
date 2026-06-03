"""基于历史周度 GMV 的简单线性外推，生成未来 N 周预测及置信区间。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from agents.nlp_agent.db import query

_WEEKLY_GMV_SQL = """
SELECT
    DATE_FORMAT(o.order_purchase_timestamp, '%%x-W%%v') AS year_week,
    SUM(oi.price + oi.freight_value) AS weekly_gmv
FROM orders o
INNER JOIN order_items oi ON o.order_id = oi.order_id
WHERE o.order_status IN (
    'delivered', 'shipped', 'created', 'approved', 'processing', 'invoiced'
)
  AND o.order_purchase_timestamp IS NOT NULL
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%%x-W%%v')
ORDER BY MIN(o.order_purchase_timestamp)
"""


def fetch_weekly_gmv() -> pd.DataFrame:
    rows = query(_WEEKLY_GMV_SQL)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["weekly_gmv"] = pd.to_numeric(df["weekly_gmv"], errors="coerce")
    return df.dropna(subset=["weekly_gmv"])


def forecast_weekly_gmv(*, horizon_weeks: int = 6, lookback_weeks: int = 26) -> dict[str, Any]:
    """
    返回可用于折线图叠加的预测结构：
    periods / values / lower / upper / method / summary
    """
    df = fetch_weekly_gmv()
    if len(df) < 8:
        return {
            "ok": False,
            "error_message": "周度 GMV 样本不足，无法预测。",
        }

    y_all = df["weekly_gmv"].astype(float).values
    lookback = min(int(lookback_weeks), len(y_all))
    y_train = y_all[-lookback:]
    x_train = np.arange(lookback, dtype=float)

    coef = np.polyfit(x_train, y_train, 1)
    fitted = np.polyval(coef, x_train)
    resid_std = float(np.std(y_train - fitted)) or float(np.mean(y_train) * 0.05)

    x_future = np.arange(lookback, lookback + int(horizon_weeks), dtype=float)
    y_pred = np.polyval(coef, x_future)
    lower = np.maximum(y_pred - 1.96 * resid_std, 0.0)
    upper = y_pred + 1.96 * resid_std

    last_label = str(df["year_week"].iloc[-1])
    periods = [f"预测+{i + 1}周" for i in range(int(horizon_weeks))]

    trend = "上升" if coef[0] > 0 else ("下降" if coef[0] < 0 else "持平")
    return {
        "ok": True,
        "method": "linear_regression_26w",
        "anchor_week": last_label,
        "periods": periods,
        "values": [float(v) for v in y_pred],
        "lower": [float(v) for v in lower],
        "upper": [float(v) for v in upper],
        "horizon_weeks": int(horizon_weeks),
        "summary_text": (
            f"基于近 {lookback} 周 GMV 线性外推，未来 {horizon_weeks} 周整体趋势{trend}；"
            f"末周预测约 {y_pred[-1]:,.0f}（95% 区间 "
            f"{lower[-1]:,.0f} ~ {upper[-1]:,.0f}）。"
        ),
    }
