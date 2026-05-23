"""
Forecast 工具：基于 mv_monthly_sales 历史 GMV 序列，给出未来 N 期（默认 6 周）基线预测。

实现策略：
- 历史粒度为月（视图 mv_monthly_sales），先用「3 期简单移动平均 + 同比同月」混合作为基线；
- 再按「等比分摊」把月度预测换算为「未来 6 周」的大致估计，便于业务人员直观对比；
- 标注 method、horizon、assumptions、forecast_values、summary，方便最终报告引用。

后续可替换为 ARIMA / Prophet；接口保持不变。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agents.decision_agent import db


class ForecastPoint(BaseModel):
    period: str = Field(description="预测期标签，如 'M+1' 或 'W+1'")
    value: float = Field(description="预测 GMV 值（单位与 total_gmv 一致）")


class ForecastOutput(BaseModel):
    method: str
    history_grain: str
    horizon: str
    history_tail: list[dict[str, Any]] = Field(default_factory=list)
    forecast_values: list[ForecastPoint] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    summary: str = ""


_HISTORY_SQL = (
    "SELECT `year_month`, `total_gmv`, `total_orders` "
    "FROM `mv_monthly_sales` ORDER BY `year_month`"
)


def _moving_average(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    tail = values[-window:]
    return sum(tail) / len(tail)


def _seasonal_naive(values: list[float], season: int = 12) -> float | None:
    """同比同月：取 N 个月前的值作为季节项；不足时返回 None。"""
    if len(values) < season:
        return None
    return values[-season]


def run_forecast(horizon_weeks: int = 6) -> dict[str, Any]:
    """对 mv_monthly_sales 做基线预测；horizon_weeks 默认 6 周。"""
    rows = db.query(_HISTORY_SQL)
    if not rows:
        return ForecastOutput(
            method="moving_average + seasonal_naive (baseline)",
            history_grain="year_month",
            horizon=f"next_{horizon_weeks}_weeks",
            assumptions=["历史数据为空，无法生成预测"],
            summary="mv_monthly_sales 没有历史记录，无法生成销售预测。",
        ).model_dump()

    months = [str(r["year_month"]) for r in rows]
    gmv = [float(r["total_gmv"] or 0.0) for r in rows]

    ma = _moving_average(gmv, window=3)
    sn = _seasonal_naive(gmv, season=12)
    base_month = 0.7 * ma + 0.3 * sn if sn is not None else ma

    # 把月度基线按 4.345 周/月折算为周度预测；做 0.98 ~ 1.02 的轻微节律
    weekly_base = base_month / 4.345
    rhythm = [1.00, 1.01, 0.99, 1.02, 0.98, 1.00, 1.00, 1.00]
    forecast_points = [
        ForecastPoint(period=f"W+{i + 1}", value=round(weekly_base * rhythm[i % len(rhythm)], 2))
        for i in range(horizon_weeks)
    ]
    total_forecast = sum(p.value for p in forecast_points)

    history_tail = [
        {"year_month": months[i], "total_gmv": round(gmv[i], 2)}
        for i in range(max(0, len(months) - 6), len(months))
    ]

    direction = (
        "上升" if gmv[-1] > _moving_average(gmv[:-1], 3)
        else "下降" if gmv[-1] < _moving_average(gmv[:-1], 3)
        else "平稳"
    )
    summary = (
        f"基于最近 {len(gmv)} 个月历史 GMV，最后 1 个月 GMV={gmv[-1]:.2f}，"
        f"近 3 月均值={ma:.2f}，"
        + (f"同比同月={sn:.2f}，" if sn is not None else "样本不足以做同比同月校准，")
        + f"未来 {horizon_weeks} 周预测合计约 {total_forecast:.2f}，整体趋势判断为「{direction}」。"
    )

    return ForecastOutput(
        method="moving_average(3) + seasonal_naive(12) baseline",
        history_grain="year_month",
        horizon=f"next_{horizon_weeks}_weeks",
        history_tail=history_tail,
        forecast_values=forecast_points,
        assumptions=[
            "采用简单移动平均与同比同月的加权基线（0.7/0.3），未拟合复杂季节项",
            "月度预测按 4.345 周/月等比折算到周度，未刻画周内节假日效应",
            "未考虑促销、外部冲击与渠道结构变化",
        ],
        summary=summary,
    ).model_dump()


def build_forecast_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=run_forecast,
        name="forecast_tool",
        description=(
            "基于预聚合视图 mv_monthly_sales 的历史 GMV 给出未来 N 周（默认 6 周）的基线预测。"
            "输出 method / history_tail / forecast_values / assumptions / summary 供决策报告引用。"
        ),
    )


if __name__ == "__main__":
    import json
    print(json.dumps(run_forecast(), ensure_ascii=False, indent=2))
