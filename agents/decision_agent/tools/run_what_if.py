from __future__ import annotations

from typing import Any

from ..schemas import WhatIfResult
from ..state import BIState


def _round_delta(value: float) -> float:
    return round(value, 4)


def run_what_if(scenario_type: str, parameters: dict[str, Any], state: BIState) -> WhatIfResult:
    analysis_result = state.get("analysis_result") or {}
    simulation_inputs = analysis_result.get("simulation_inputs") or {}

    if scenario_type == "remove_top_bad_sellers":
        seller_metrics = simulation_inputs.get("seller_quality_impact") or {}
        baseline_review = float(seller_metrics.get("baseline_avg_review_score", 0.0))
        simulated_review = float(
            seller_metrics.get("remove_top_n_avg_review_score", baseline_review)
        )
        baseline_negative = float(seller_metrics.get("baseline_negative_rate", 0.0))
        simulated_negative = float(
            seller_metrics.get("remove_top_n_negative_rate", baseline_negative)
        )
        baseline_gmv = float(seller_metrics.get("baseline_gmv", 0.0))
        simulated_gmv = float(seller_metrics.get("remove_top_n_gmv", baseline_gmv))
        top_n = int(parameters.get("top_n", seller_metrics.get("top_n", 20)))
        return WhatIfResult(
            scenario_type=scenario_type,
            parameters={"top_n": top_n},
            baseline_metrics={
                "avg_review_score": baseline_review,
                "negative_rate": baseline_negative,
                "gmv": baseline_gmv,
            },
            simulated_metrics={
                "avg_review_score": simulated_review,
                "negative_rate": simulated_negative,
                "gmv": simulated_gmv,
            },
            delta_metrics={
                "avg_review_score": _round_delta(simulated_review - baseline_review),
                "negative_rate": _round_delta(simulated_negative - baseline_negative),
                "gmv": _round_delta(simulated_gmv - baseline_gmv),
            },
            summary_text=(
                f"若下架 Top {top_n} 高差评卖家，平均评分预计由 {baseline_review:.2f} 提升到 "
                f"{simulated_review:.2f}，负面率变化 {simulated_negative - baseline_negative:+.2%}，"
                f"GMV 变化 {simulated_gmv - baseline_gmv:+.2f}。"
            ),
        )

    if scenario_type == "improve_delivery_days":
        delivery_metrics = simulation_inputs.get("delivery_improvement") or {}
        improvement_days = float(parameters.get("improvement_days", 1.0))
        baseline_days = float(delivery_metrics.get("baseline_avg_delivery_days", 0.0))
        baseline_on_time = float(delivery_metrics.get("baseline_on_time_rate", 0.0))
        baseline_negative = float(delivery_metrics.get("baseline_delivery_negative_share", 0.0))
        on_time_per_day = float(delivery_metrics.get("on_time_rate_gain_per_day", 0.03))
        negative_per_day = float(delivery_metrics.get("negative_share_drop_per_day", 0.02))
        simulated_days = max(0.0, baseline_days - improvement_days)
        simulated_on_time = min(1.0, baseline_on_time + improvement_days * on_time_per_day)
        simulated_negative = max(0.0, baseline_negative - improvement_days * negative_per_day)
        return WhatIfResult(
            scenario_type=scenario_type,
            parameters={"improvement_days": improvement_days},
            baseline_metrics={
                "avg_delivery_days": baseline_days,
                "on_time_rate": baseline_on_time,
                "delivery_negative_share": baseline_negative,
            },
            simulated_metrics={
                "avg_delivery_days": simulated_days,
                "on_time_rate": simulated_on_time,
                "delivery_negative_share": simulated_negative,
            },
            delta_metrics={
                "avg_delivery_days": _round_delta(simulated_days - baseline_days),
                "on_time_rate": _round_delta(simulated_on_time - baseline_on_time),
                "delivery_negative_share": _round_delta(
                    simulated_negative - baseline_negative
                ),
            },
            summary_text=(
                f"若平均配送时长缩短 {improvement_days:.1f} 天，准时率预计由 {baseline_on_time:.2%} "
                f"提升到 {simulated_on_time:.2%}，配送相关负面主题占比预计下降到 {simulated_negative:.2%}。"
            ),
        )

    return WhatIfResult(
        scenario_type=scenario_type,
        parameters=parameters,
        summary_text="当前未命中已实现的 What-if 场景。",
    )
