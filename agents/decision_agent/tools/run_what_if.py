from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..schemas import WhatIfResult


def _round_delta(value: float) -> float:
    return round(value, 4)


def _missing_inputs(*, group_name: str, metrics: Mapping[str, Any], keys: list[str]) -> list[str]:
    return [
        f"analysis_result.simulation_inputs.{group_name}.{key}"
        for key in keys
        if metrics.get(key) in (None, "")
    ]


def _missing_result(
    scenario_type: str,
    parameters: dict[str, Any],
    missing_inputs: list[str],
) -> WhatIfResult:
    return WhatIfResult(
        scenario_type=scenario_type,
        status="missing_inputs",
        parameters=parameters,
        missing_inputs=missing_inputs,
        summary_text=(
            "本次未运行 What-if：缺少可支撑该场景的模拟输入，"
            f"需补充 {', '.join(missing_inputs)}。"
        ),
        limitations=["未使用默认 0 值替代缺失指标，避免产生误导性模拟结果。"],
    )


def run_what_if(
    scenario_type: str,
    parameters: dict[str, Any],
    state: Mapping[str, Any],
) -> WhatIfResult:
    analysis_result = state.get("analysis_result") or {}
    simulation_inputs = analysis_result.get("simulation_inputs") or {}

    if scenario_type == "remove_top_bad_sellers":
        seller_metrics = simulation_inputs.get("seller_quality_impact") or {}
        required = [
            "baseline_avg_review_score",
            "remove_top_n_avg_review_score",
            "baseline_negative_rate",
            "remove_top_n_negative_rate",
            "baseline_gmv",
            "remove_top_n_gmv",
        ]
        missing = _missing_inputs(
            group_name="seller_quality_impact",
            metrics=seller_metrics,
            keys=required,
        )
        if missing:
            return _missing_result(scenario_type, parameters, missing)
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
            status="run",
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
            limitations=["静态反事实估计，不重新分配被剔除卖家的需求。"],
        )

    if scenario_type == "improve_delivery_days":
        delivery_metrics = simulation_inputs.get("delivery_improvement") or {}
        required = [
            "baseline_avg_delivery_days",
            "baseline_on_time_rate",
            "baseline_delivery_negative_share",
        ]
        missing = _missing_inputs(
            group_name="delivery_improvement",
            metrics=delivery_metrics,
            keys=required,
        )
        if missing:
            return _missing_result(scenario_type, parameters, missing)
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
            status="run",
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
            limitations=["启发式估计，只反映当前输入快照下的方向性影响。"],
        )

    if scenario_type == "improve_category_quality":
        category_metrics = simulation_inputs.get("category_quality_impact") or {}
        required = [
            "category",
            "baseline_negative_rate",
            "improved_negative_rate",
            "baseline_bad_review_count",
            "improved_bad_review_count",
        ]
        missing = _missing_inputs(
            group_name="category_quality_impact",
            metrics=category_metrics,
            keys=required,
        )
        if missing:
            return _missing_result(scenario_type, parameters, missing)
        category = str(category_metrics.get("category"))
        baseline_negative = float(category_metrics.get("baseline_negative_rate", 0.0))
        improved_negative = float(
            category_metrics.get("improved_negative_rate", baseline_negative)
        )
        baseline_bad_reviews = float(
            category_metrics.get("baseline_bad_review_count", 0.0)
        )
        improved_bad_reviews = float(
            category_metrics.get("improved_bad_review_count", baseline_bad_reviews)
        )
        baseline_gmv = category_metrics.get("baseline_gmv")
        projected_gmv = category_metrics.get("projected_gmv")
        baseline_metrics = {
            "category": category,
            "negative_rate": baseline_negative,
            "bad_review_count": baseline_bad_reviews,
        }
        simulated_metrics = {
            "category": category,
            "negative_rate": improved_negative,
            "bad_review_count": improved_bad_reviews,
        }
        delta_metrics = {
            "negative_rate": _round_delta(improved_negative - baseline_negative),
            "bad_review_count": _round_delta(improved_bad_reviews - baseline_bad_reviews),
        }
        if baseline_gmv not in (None, "") and projected_gmv not in (None, ""):
            baseline_gmv_f = float(baseline_gmv)
            projected_gmv_f = float(projected_gmv)
            baseline_metrics["gmv"] = baseline_gmv_f
            simulated_metrics["gmv"] = projected_gmv_f
            delta_metrics["gmv"] = _round_delta(projected_gmv_f - baseline_gmv_f)
        return WhatIfResult(
            scenario_type=scenario_type,
            status="run",
            parameters={
                "target_negative_rate_drop": float(
                    parameters.get("target_negative_rate_drop", 0.05)
                )
            },
            baseline_metrics=baseline_metrics,
            simulated_metrics=simulated_metrics,
            delta_metrics=delta_metrics,
            summary_text=(
                f"若对 {category} 品类执行质检、差评 SKU 审核和详情页修正，"
                f"负面率预计由 {baseline_negative:.2%} 降至 {improved_negative:.2%}，"
                f"差评数变化 {improved_bad_reviews - baseline_bad_reviews:+.0f}。"
            ),
            limitations=[
                "静态品类治理估计，未模拟需求迁移、库存变化或卖家退出后的替代供给。",
            ],
        )

    return WhatIfResult(
        scenario_type=scenario_type,
        status="not_applicable",
        parameters=parameters,
        summary_text="当前未命中已实现的 What-if 场景。",
    )
