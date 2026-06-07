from __future__ import annotations

from agents.viz_agent.forecast import gmv_forecast_result_payload


def test_gmv_forecast_result_payload_has_weekly_table():
    fc = {
        "ok": True,
        "method": "linear_regression_26w",
        "method_zh": "近 26 周周度 GMV 一元线性回归外推",
        "periods": ["预测+1周", "预测+2周"],
        "values": [100.0, 110.0],
        "lower": [80.0, 85.0],
        "upper": [120.0, 130.0],
        "horizon_weeks": 2,
        "trend_direction": "up",
        "trend_zh": "上升",
        "weekly_forecast": [
            {"week_label": "预测+1周", "forecast_gmv": 100.0, "lower_95": 80.0, "upper_95": 120.0},
            {"week_label": "预测+2周", "forecast_gmv": 110.0, "lower_95": 85.0, "upper_95": 130.0},
        ],
        "summary_text": "测试摘要",
    }
    payload = gmv_forecast_result_payload(fc)
    assert len(payload["weekly_forecast"]) == 2
    assert payload["forecast_values"] == [100.0, 110.0]
    assert payload["method_zh"]
