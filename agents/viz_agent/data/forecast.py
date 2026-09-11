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
    trend_en = "up" if coef[0] > 0 else ("down" if coef[0] < 0 else "flat")
    weekly_rows = [
        {
            "week_label": periods[i],
            "forecast_gmv": float(y_pred[i]),
            "lower_95": float(lower[i]),
            "upper_95": float(upper[i]),
        }
        for i in range(int(horizon_weeks))
    ]
    return {
        "ok": True,
        "method": "linear_regression_26w",
        "method_zh": f"近 {lookback} 周周度 GMV 一元线性回归外推",
        "anchor_week": last_label,
        "last_actual_week": last_label,
        "last_actual_gmv": float(y_train[-1]),
        "lookback_weeks": int(lookback),
        "slope_per_week": float(coef[0]),
        "residual_std": float(resid_std),
        "periods": periods,
        "values": [float(v) for v in y_pred],
        "lower": [float(v) for v in lower],
        "upper": [float(v) for v in upper],
        "horizon_weeks": int(horizon_weeks),
        "trend_direction": trend_en,
        "trend_zh": trend,
        "weekly_forecast": weekly_rows,
        "summary_text": (
            f"基于近 {lookback} 周 GMV 线性外推，未来 {horizon_weeks} 周整体趋势{trend}；"
            f"末周预测约 {y_pred[-1]:,.0f}（95% 区间 "
            f"{lower[-1]:,.0f} ~ {upper[-1]:,.0f}）。"
        ),
    }


def gmv_forecast_result_payload(fc: dict[str, Any]) -> dict[str, Any]:
    """将 forecast_weekly_gmv 输出转为 decision / synthesize 共用的 forecast_result。"""
    if not fc.get("ok"):
        return {}
    values = fc.get("values") or []
    trend = str(fc.get("trend_direction") or "flat")
    risk_flags: list[str] = []
    if trend in {"down", "flat"}:
        risk_flags.append("周度 GMV 外推趋势偏弱，需关注增长放缓风险")
    return {
        "ok": True,
        "method": str(fc.get("method") or "linear_regression_26w"),
        "method_zh": str(fc.get("method_zh") or ""),
        "horizon": f"{fc.get('horizon_weeks') or 6} weeks",
        "horizon_weeks": int(fc.get("horizon_weeks") or 6),
        "summary_text": str(fc.get("summary_text") or ""),
        "forecast_values": values,
        "values": values,
        "periods": list(fc.get("periods") or []),
        "lower": fc.get("lower") or [],
        "upper": fc.get("upper") or [],
        "trend_direction": trend,
        "trend_zh": str(fc.get("trend_zh") or ""),
        "weekly_forecast": list(fc.get("weekly_forecast") or []),
        "lookback_weeks": fc.get("lookback_weeks"),
        "slope_per_week": fc.get("slope_per_week"),
        "last_actual_week": fc.get("last_actual_week"),
        "last_actual_gmv": fc.get("last_actual_gmv"),
        "residual_std": fc.get("residual_std"),
        "risk_flags": risk_flags,
    }
