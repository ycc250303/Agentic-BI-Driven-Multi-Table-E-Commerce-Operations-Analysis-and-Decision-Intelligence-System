from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..schemas import WhatIfComputation, WhatIfPlan, WhatIfResult


def _round_metric(value: float) -> float:
    return round(value, 4)


def _metric_value_name(metric: str) -> str:
    return metric.strip() or "metric"


def _looks_like_rate(metric: str, unit: str) -> bool:
    text = f"{metric} {unit}".lower()
    return any(token in text for token in ("rate", "share", "ratio", "pct", "率", "占比"))


def _apply_formula(computation: WhatIfComputation) -> float:
    baseline = float(computation.baseline_value)
    change = float(computation.change_value)
    formula = computation.formula
    if formula == "add":
        value = baseline + change
    elif formula == "subtract":
        value = baseline - change
    elif formula == "multiply":
        value = baseline * change
    elif formula == "percent_change":
        value = baseline * (1.0 + change)
    elif formula == "percentage_point_change":
        value = baseline + change
    else:  # pragma: no cover - Literal validation should make this unreachable.
        value = baseline
    if _looks_like_rate(computation.target_metric, computation.unit):
        value = max(0.0, min(1.0, value))
    return value


def _missing_for_computation(computation: WhatIfComputation) -> list[str]:
    missing: list[str] = []
    metric = _metric_value_name(computation.target_metric)
    if computation.baseline_value is None:
        missing.append(f"what_if_plan.computations.{metric}.baseline_value")
    if computation.change_value is None:
        missing.append(f"what_if_plan.computations.{metric}.change_value")
    if not computation.baseline_source:
        missing.append(f"what_if_plan.computations.{metric}.baseline_source")
    if not computation.change_source:
        missing.append(f"what_if_plan.computations.{metric}.change_source")
    return missing


def _plan_parameters(plan: WhatIfPlan) -> dict[str, Any]:
    return {
        "plan_type": plan.plan_type,
        "question": plan.question,
        "interventions": [
            intervention.model_dump(mode="json") for intervention in plan.interventions
        ],
        "target_metrics": list(plan.target_metrics),
        "assumptions": list(plan.assumptions),
    }


def _not_run_result(plan: WhatIfPlan) -> WhatIfResult:
    return WhatIfResult(
        scenario_type="generic_what_if",
        status="not_run",
        parameters=_plan_parameters(plan),
        summary_text=(
            plan.reasoning_summary or "用户本轮没有提出明确的 What-if 模拟问题。"
        ),
        limitations=list(plan.limitations),
    )


def _missing_result(plan: WhatIfPlan, missing_inputs: list[str]) -> WhatIfResult:
    unique_missing = list(dict.fromkeys(missing_inputs))
    return WhatIfResult(
        scenario_type="missing_inputs",
        status="missing_inputs",
        parameters=_plan_parameters(plan),
        missing_inputs=unique_missing,
        summary_text=(
            "已识别为 What-if 问题，但当前证据不足以进行定量模拟；"
            f"需要补充：{', '.join(unique_missing)}。"
        ),
        limitations=[
            "未使用默认值或经验弹性替代缺失指标，避免产生误导性模拟结果。",
            *plan.limitations,
        ],
    )


def _directional_result(plan: WhatIfPlan) -> WhatIfResult:
    summary = plan.reasoning_summary or "当前只能给出方向性判断，无法形成定量模拟。"
    missing = list(dict.fromkeys(plan.missing_inputs))
    return WhatIfResult(
        scenario_type="directional_what_if",
        status="directional_only",
        parameters=_plan_parameters(plan),
        summary_text=summary,
        limitations=[
            "缺少可计算的 baseline/change/elasticity，未输出模拟数值。",
            *plan.limitations,
        ],
        missing_inputs=missing,
    )


def run_what_if(plan: WhatIfPlan | Mapping[str, Any], state: Mapping[str, Any] | None = None) -> WhatIfResult:
    """Run a generic What-if plan.

    `state` is accepted for future evidence lookups. The current runner only
    executes computations whose baseline and change values are explicit in the
    plan, so it does not infer hidden business parameters from state.
    """
    del state
    plan = plan if isinstance(plan, WhatIfPlan) else WhatIfPlan.model_validate(plan)
    if not plan.has_what_if_intent:
        return _not_run_result(plan)

    missing_inputs = list(plan.missing_inputs)
    for computation in plan.computations:
        missing_inputs.extend(_missing_for_computation(computation))

    if missing_inputs:
        if plan.directional_only and not plan.can_quantify:
            return _directional_result(plan)
        return _missing_result(plan, missing_inputs)

    if not plan.can_quantify or not plan.computations:
        if plan.directional_only:
            return _directional_result(plan)
        return _missing_result(
            plan,
            plan.missing_inputs or ["what_if_plan.computations"],
        )

    baseline_metrics: dict[str, Any] = {}
    simulated_metrics: dict[str, Any] = {}
    delta_metrics: dict[str, Any] = {}
    for computation in plan.computations:
        metric = _metric_value_name(computation.target_metric)
        baseline = float(computation.baseline_value)
        simulated = _apply_formula(computation)
        baseline_metrics[metric] = _round_metric(baseline)
        simulated_metrics[metric] = _round_metric(simulated)
        delta_metrics[metric] = _round_metric(simulated - baseline)

    metric_text = "；".join(
        f"{metric}: {baseline_metrics[metric]} -> {simulated_metrics[metric]} "
        f"({delta_metrics[metric]:+g})"
        for metric in simulated_metrics
    )
    return WhatIfResult(
        scenario_type="quantified_what_if",
        status="run",
        parameters=_plan_parameters(plan),
        baseline_metrics=baseline_metrics,
        simulated_metrics=simulated_metrics,
        delta_metrics=delta_metrics,
        summary_text=(
            plan.reasoning_summary
            or f"基于用户假设和已有证据完成通用 What-if 计算：{metric_text}。"
        ),
        limitations=[
            "通用 What-if 只执行计划中显式给出的简单计算，不推断未提供的业务弹性。",
            *plan.limitations,
        ],
    )
