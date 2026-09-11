"""决策 Agent 输入告警：在补齐流程之后，对仍缺失的必需上游结果如实告警。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.decision_agent.schemas import DecisionInputs
from agents.nlp_agent.run import should_run_nlp


@dataclass
class PipelineContext:
    suggested_agents: list[str] = field(default_factory=list)
    agents_done: dict[str, bool] = field(default_factory=dict)
    forecast_attempted: bool = False


def has_nlp_payload(nlp: dict) -> bool:
    if not nlp:
        return False
    if str(nlp.get("summary_text") or nlp.get("summary") or "").strip():
        return True
    if nlp.get("negative_topics") or nlp.get("topic_distribution"):
        return True
    if nlp.get("complaints_by_category") or nlp.get("worst_categories"):
        return True
    bertopic = nlp.get("topics_bertopic") or {}
    if bertopic.get("topics"):
        return True
    wc = nlp.get("wordcloud") or {}
    if wc.get("positive") or wc.get("negative"):
        return True
    return False


def has_forecast_payload(forecast: dict) -> bool:
    if not forecast:
        return False
    if str(forecast.get("summary_text") or forecast.get("summary") or "").strip():
        return True
    if forecast.get("forecast_values") or forecast.get("values"):
        return True
    if forecast.get("risk_flags"):
        return True
    if str(forecast.get("trend_direction") or "").strip():
        return True
    return False


def _pipeline_from_dict(raw: dict[str, Any] | None) -> PipelineContext:
    raw = raw or {}
    done = raw.get("agents_done") or {}
    return PipelineContext(
        suggested_agents=list(raw.get("suggested_agents") or []),
        agents_done={str(k): bool(v) for k, v in done.items()},
        forecast_attempted=bool(raw.get("forecast_attempted")),
    )


def nlp_was_expected(inputs: DecisionInputs, pipeline: PipelineContext) -> bool:
    if should_run_nlp(inputs.user_query, inputs.intent):
        return True
    if "nlp" in pipeline.suggested_agents:
        return True
    if pipeline.agents_done.get("nlp"):
        return True
    return inputs.intent in ("diagnostic", "prescriptive")


def forecast_was_expected(inputs: DecisionInputs, pipeline: PipelineContext) -> bool:
    if inputs.intent == "predictive":
        return True
    return pipeline.forecast_attempted


def collect_input_warnings(
    inputs: DecisionInputs,
    *,
    pipeline: dict[str, Any] | PipelineContext | None = None,
) -> list[str]:
    ctx = (
        pipeline
        if isinstance(pipeline, PipelineContext)
        else _pipeline_from_dict(pipeline)
    )
    warnings: list[str] = []
    if not inputs.analysis_result:
        warnings.append("缺少 analysis_result，Decision-Agent 无法完成核心证据整理。")

    if nlp_was_expected(inputs, ctx) and not has_nlp_payload(inputs.nlp_result):
        warnings.append(
            "缺少 nlp_result：评论洞察 Agent 未产出有效结果，差评根因解释不完整。"
        )

    if forecast_was_expected(inputs, ctx) and not has_forecast_payload(
        inputs.forecast_result
    ):
        warnings.append(
            "缺少 forecast_result：预测模块未产出有效结果，无法给出定量趋势预警。"
        )

    if not inputs.visualization_result:
        warnings.append("缺少 visualization_result，本次建议不会引用图表结论。")
    return warnings
