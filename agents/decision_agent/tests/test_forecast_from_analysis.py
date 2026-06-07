from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agents.decision_agent.forecast_from_analysis import build_bad_review_forecast_result


def test_build_bad_review_forecast_from_sql_csv(tmp_path: Path):
    csv_path = tmp_path / "trend.csv"
    rows = []
    for month, rate in [
        ("2018-05", 0.10),
        ("2018-06", 0.11),
        ("2018-07", 0.12),
        ("2018-08", 0.25),
        ("2018-09", 0.26),
        ("2018-10", 0.27),
    ]:
        rows.append(
            {
                "year_month": month,
                "product_category_english": "tools",
                "bad_review_rate": rate,
            }
        )
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    sql_runs = [
        {
            "execute_sql_json": json.dumps(
                {
                    "ok": True,
                    "results": [
                        {
                            "ok": True,
                            "result_csv_path": str(csv_path),
                            "row_count_returned": len(rows),
                        }
                    ],
                }
            )
        }
    ]
    out = build_bad_review_forecast_result(
        user_query="预测未来各品类差评订单数变化趋势",
        intent="predictive",
        sql_runs=sql_runs,
    )
    assert out.get("ok")
    assert out.get("summary_text")
    assert out.get("trend_direction") == "up"
    assert out.get("risk_flags")
