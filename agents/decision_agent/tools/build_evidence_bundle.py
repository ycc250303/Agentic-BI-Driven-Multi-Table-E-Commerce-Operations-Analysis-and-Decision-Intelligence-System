from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..schemas import DecisionSignal, EvidenceBundle


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _cap_score(score: float) -> float:
    return max(0.0, min(1.0, round(score, 4)))


def _metadata(
    *,
    evidence_strength: str = "direct",
    subject_match: str = "unknown",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "evidence_strength": evidence_strength,
        "subject_match": subject_match,
        **{k: v for k, v in extra.items() if v is not None and v != ""},
    }


def _iter_negative_topics(raw_topics: Any) -> list[dict[str, Any]]:
    if isinstance(raw_topics, dict):
        total = sum(
            value for value in raw_topics.values() if isinstance(value, int | float)
        )
        return [
            {
                "topic": str(topic),
                "count": int(count),
                "share": float(count) / total if total else 0.0,
            }
            for topic, count in raw_topics.items()
            if isinstance(count, int | float)
        ]
    if isinstance(raw_topics, list):
        return [topic for topic in raw_topics if isinstance(topic, dict)]
    return []


def build_evidence_bundle(state: Mapping[str, Any]) -> EvidenceBundle:
    user_query = str(state.get("user_query", "")).strip()
    analysis_result = state.get("analysis_result") or {}
    nlp_result = state.get("nlp_result") or {}
    forecast_result = state.get("forecast_result") or {}
    visualization_result = state.get("visualization_result") or {}
    signals: list[DecisionSignal] = []

    kpis = analysis_result.get("kpis") or {}
    findings = analysis_result.get("findings") or []

    on_time_rate = _safe_float(kpis.get("on_time_rate"))
    if on_time_rate is not None and on_time_rate < 0.82:
        gap = 0.82 - on_time_rate
        signals.append(
            DecisionSignal(
                domain="delivery",
                signal="on_time_rate below benchmark",
                value=on_time_rate,
                benchmark=0.82,
                severity_score=_cap_score(gap / 0.22 + 0.2),
                evidence_text=f"准时交付率仅为 {on_time_rate:.2%}，低于 82% 阈值。",
                metadata=_metadata(signal_family="delivery_performance"),
            )
        )

    avg_delivery_days = _safe_float(kpis.get("avg_delivery_days"))
    if avg_delivery_days is not None and avg_delivery_days > 8.0:
        delta = avg_delivery_days - 8.0
        signals.append(
            DecisionSignal(
                domain="delivery",
                signal="avg_delivery_days above benchmark",
                value=avg_delivery_days,
                benchmark=8.0,
                severity_score=_cap_score(delta / 6.0 + 0.25),
                evidence_text=f"平均配送时长 {avg_delivery_days:.1f} 天，高于 8 天基准。",
                metadata=_metadata(signal_family="delivery_performance"),
            )
        )

    for finding in findings:
        topic = str(finding.get("topic") or "").lower()
        metric = str(finding.get("metric") or "").lower()
        evidence = str(finding.get("evidence") or "").strip()
        scope = str(finding.get("scope") or "").strip()
        value = _safe_float(finding.get("value"))
        gap = _safe_float(finding.get("gap"))
        benchmark = _safe_float(finding.get("benchmark"))

        if topic == "delivery" or metric in {"on_time_rate", "avg_delivery_days"}:
            severity = 0.55
            if gap is not None and gap < 0:
                severity = _cap_score(abs(gap) / 0.2 + 0.25)
            elif gap is not None and gap > 0:
                severity = _cap_score(gap / 5.0 + 0.25)
            signals.append(
                DecisionSignal(
                    domain="delivery",
                    signal=f"{metric or topic} finding",
                    value=value,
                    benchmark=benchmark,
                    severity_score=severity,
                    evidence_text=evidence or f"{scope} 存在配送表现异常。",
                    metadata=_metadata(
                        signal_family="delivery_performance",
                        subject_match="exact" if scope and scope.lower() in user_query.lower() else "unknown",
                        scope=scope,
                    ),
                )
            )

        if topic == "delivery" and metric in {
            "delayed_orders",
            "delayed_orders_count",
            "delay_rate",
            "state_delay_rate",
            "delay_share",
        }:
            severity = 0.6
            if gap is not None and value is not None and value > 0:
                severity = _cap_score(abs(gap) / max(value, 1.0) + 0.45)
            signals.append(
                DecisionSignal(
                    domain="delivery",
                    signal="delayed_orders finding",
                    value=value,
                    benchmark=benchmark,
                    severity_score=severity,
                    evidence_text=evidence or f"{scope} 延迟订单数偏高。",
                    metadata=_metadata(
                        signal_family="delivery_performance",
                        subject_match="exact" if scope and scope.lower() in user_query.lower() else "unknown",
                        scope=scope,
                    ),
                )
            )

        if topic == "seller" or metric == "avg_review_score":
            severity = 0.5
            if value is not None and value < 3.6:
                severity = _cap_score((3.6 - value) / 1.2 + 0.35)
                signals.append(
                    DecisionSignal(
                        domain="seller",
                        signal="avg_review_score below threshold",
                        value=value,
                        benchmark=3.6,
                        severity_score=severity,
                        evidence_text=evidence or f"{scope} 卖家评分偏低。",
                        metadata=_metadata(
                            signal_family="seller_quality",
                            subject_match="exact" if scope and scope.lower() in user_query.lower() else "unknown",
                            scope=scope,
                        ),
                    )
                )

        if topic == "category":
            severity = 0.5
            if "decline" in metric or "down" in metric:
                severity = _cap_score(abs(gap or 0.15) + 0.4)
                signals.append(
                    DecisionSignal(
                        domain="category",
                        signal="sales decline",
                        value=value,
                        benchmark=benchmark,
                        severity_score=severity,
                        evidence_text=evidence or f"{scope} 品类销量下滑。",
                        metadata=_metadata(
                            signal_family="category_performance",
                            subject_match="exact" if scope and scope.lower() in user_query.lower() else "unknown",
                            scope=scope,
                        ),
                    )
                )
            if metric in {"bad_review_rate", "negative_rate"} and value is not None:
                signals.append(
                    DecisionSignal(
                        domain="category",
                        signal="negative quality rate",
                        value=value,
                        benchmark=benchmark,
                        severity_score=_cap_score(max(value - 0.2, 0.0) / 0.3 + 0.45),
                        evidence_text=evidence or f"{scope} 品类差评率偏高。",
                        metadata=_metadata(
                            signal_family="category_quality",
                            subject_match="exact" if scope and scope.lower() in user_query.lower() else "unknown",
                            scope=scope,
                        ),
                    )
                )
            if metric in {"bad_review_count", "negative_review_count"}:
                severity = 0.6 if value is None else _cap_score(min(value / 2000.0, 0.4) + 0.45)
                signals.append(
                    DecisionSignal(
                        domain="category",
                        signal="bad_review_count high",
                        value=value,
                        benchmark=benchmark,
                        severity_score=severity,
                        evidence_text=evidence or f"{scope} 品类差评数量偏高。",
                        metadata=_metadata(
                            signal_family="category_quality",
                            subject_match="exact" if scope and scope.lower() in user_query.lower() else "unknown",
                            scope=scope,
                        ),
                    )
                )

        if topic == "region":
            signals.append(
                DecisionSignal(
                    domain="region",
                    signal="high gmv with high negative rate",
                    value=value,
                    benchmark=benchmark,
                    severity_score=_cap_score(abs(gap or 0.12) + 0.45),
                    evidence_text=evidence or f"{scope} 区域销售与口碑存在冲突。",
                    metadata=_metadata(
                        signal_family="regional_sentiment",
                        subject_match="exact" if scope and scope.lower() in user_query.lower() else "unknown",
                        scope=scope,
                    ),
                )
            )

    # BERTopic 发现 40 个细粒度主题，单个占比最高 ~14%。
    # 按 4 大类聚合后判断（基于 review_topic_meta 表 40 个真实标签做葡语词根分类）。
    topic_delivery_share = 0.0
    topic_quality_share = 0.0
    topic_wrong_item_share = 0.0
    topic_service_share = 0.0
    topic_delivery_count = 0
    topic_quality_count = 0
    topic_wrong_item_count = 0
    topic_service_count = 0

    for topic in _iter_negative_topics(nlp_result.get("negative_topics")):
        name = str(topic.get("topic") or "").lower()
        share = _safe_float(topic.get("share")) or 0.0
        count = int(topic.get("count") or 0)
        if any(kw in name for kw in (
            "entrega", "recebi", "demora", "prazo", "chegou",
            "entregue", "aguardando", "dias", "data", "correios",
            "delivery", "delay", "late", "arrival", "not_received",
            "not received", "shipping", "shipment",
        )):
            topic_delivery_share += share
            topic_delivery_count += count
        if any(kw in name for kw in (
            "quebrado", "quebrada", "qualidade", "péssima", "pessima",
            "defeito", "defeitos", "danificado", "material", "usado",
            "finas", "fino", "plástico", "plastico",
            "quality", "defect", "broken", "damaged", "missing_parts",
            "missing parts",
        )):
            topic_quality_share += share
            topic_quality_count += count
        if any(kw in name for kw in (
            "diferente", "propaganda", "enganosa", "foto", "imagem",
            "cor", "tamanho", "errada", "anunciado", "réplica", "replica",
            "wrong_item", "wrong item", "misleading",
        )):
            topic_wrong_item_share += share
            topic_wrong_item_count += count
        if any(kw in name for kw in (
            "cancelamento", "cancelar", "cancelei", "dinheiro",
            "volta", "cartão", "cartao", "crédito", "credito",
            "estorno", "devolver", "troca", "trocar", "loja",
            "refund", "customer_service", "customer service", "cancel",
        )):
            topic_service_share += share
            topic_service_count += count

    if topic_delivery_share >= 0.25:
        signals.append(
            DecisionSignal(
                domain="delivery",
                signal="negative topic share high",
                value=topic_delivery_share,
                benchmark=0.25,
                severity_score=_cap_score((topic_delivery_share - 0.25) / 0.3 + 0.45),
                evidence_text=(
                    f"负面评论中配送/物流相关主题（未收到货、延迟、超时等）"
                    f"合计占比 {topic_delivery_share:.1%}（{topic_delivery_count} 条），"
                    f"超过 25% 基准线。"
                ),
                metadata=_metadata(signal_family="negative_topic"),
            )
        )
    if topic_quality_share >= 0.15:
        signals.append(
            DecisionSignal(
                domain="category",
                signal="negative quality rate",
                value=topic_quality_share,
                benchmark=0.15,
                severity_score=_cap_score((topic_quality_share - 0.15) / 0.25 + 0.4),
                evidence_text=(
                    f"负面评论中产品质量相关主题（破损、缺陷、材质差等）"
                    f"合计占比 {topic_quality_share:.1%}（{topic_quality_count} 条），"
                    f"超过 15% 基准线。"
                ),
                metadata=_metadata(signal_family="negative_topic"),
            )
        )
    if topic_wrong_item_share >= 0.10:
        signals.append(
            DecisionSignal(
                domain="category",
                signal="wrong item / misleading listing",
                value=topic_wrong_item_share,
                benchmark=0.10,
                severity_score=_cap_score((topic_wrong_item_share - 0.10) / 0.2 + 0.4),
                evidence_text=(
                    f"负面评论中货不对板/描述不符相关主题（发错货、图片与实物不符等）"
                    f"合计占比 {topic_wrong_item_share:.1%}（{topic_wrong_item_count} 条），"
                    f"超过 10% 基准线。"
                ),
                metadata=_metadata(signal_family="negative_topic"),
            )
        )
    if topic_service_share >= 0.10:
        signals.append(
            DecisionSignal(
                domain="seller",
                signal="service / refund complaint",
                value=topic_service_share,
                benchmark=0.10,
                severity_score=_cap_score((topic_service_share - 0.10) / 0.2 + 0.35),
                evidence_text=(
                    f"负面评论中售后/退款/取消相关主题"
                    f"合计占比 {topic_service_share:.1%}（{topic_service_count} 条），"
                    f"超过 10% 基准线。"
                ),
                metadata=_metadata(signal_family="negative_topic"),
            )
        )

    for category in nlp_result.get("worst_categories") or []:
        negative_rate = _safe_float(category.get("negative_rate")) or 0.0
        category_name = str(category.get("category") or "unknown")
        if negative_rate >= 0.25:
            signals.append(
                DecisionSignal(
                    domain="category",
                    signal="negative quality rate",
                    value=negative_rate,
                    benchmark=0.25,
                    severity_score=_cap_score((negative_rate - 0.25) / 0.25 + 0.5),
                    evidence_text=f"{category_name} 品类负面评论率为 {negative_rate:.2%}，高于 25% 阈值。",
                    metadata=_metadata(
                        signal_family="category_quality",
                        evidence_strength=(
                            "direct"
                            if category_name.lower() in user_query.lower()
                            else "proxy"
                        ),
                        subject_match=(
                            "exact"
                            if category_name.lower() in user_query.lower()
                            else "partial"
                        ),
                        category=category_name,
                    ),
                )
            )

    for region in nlp_result.get("worst_states") or []:
        negative_rate = _safe_float(region.get("negative_rate")) or 0.0
        state_name = str(region.get("state") or "unknown")
        if negative_rate >= 0.22:
            signals.append(
                DecisionSignal(
                    domain="region",
                    signal="regional negative sentiment",
                    value=negative_rate,
                    benchmark=0.22,
                    severity_score=_cap_score((negative_rate - 0.22) / 0.25 + 0.45),
                    evidence_text=f"{state_name} 州负面评论率达 {negative_rate:.2%}，显著高于 22% 阈值。",
                    metadata=_metadata(
                        signal_family="regional_sentiment",
                        subject_match=(
                            "exact"
                            if state_name.lower() in user_query.lower()
                            else "unknown"
                        ),
                        state=state_name,
                    ),
                )
            )

    trend_direction = str(forecast_result.get("trend_direction") or "").lower()
    risk_flags = forecast_result.get("risk_flags") or []
    if trend_direction in {"down", "flat"} or risk_flags:
        severity = 0.5 if trend_direction == "flat" else 0.72
        if any("放缓" in str(flag) or "slow" in str(flag).lower() for flag in risk_flags):
            severity = max(severity, 0.75)
        summary_text = str(forecast_result.get("summary_text") or "").strip()
        evidence_text = summary_text or "预测结果提示短期增长存在放缓风险。"
        if risk_flags:
            evidence_text = f"{evidence_text} 风险提示：{'；'.join(str(flag) for flag in risk_flags)}"
        signals.append(
            DecisionSignal(
                domain="forecast",
                signal="growth slowdown",
                value=trend_direction,
                benchmark="up",
                severity_score=severity,
                evidence_text=evidence_text,
                metadata=_metadata(signal_family="forecast"),
            )
        )

    what_if_result = state.get("what_if_result") or {}
    if what_if_result:
        scenario_type = str(
            what_if_result.get("scenario_type")
            or what_if_result.get("scenario")
            or ""
        ).lower()
        summary_text = str(
            what_if_result.get("summary_text") or what_if_result.get("summary") or ""
        ).strip()
        if "seller" in scenario_type or "seller" in summary_text.lower():
            baseline = what_if_result.get("baseline_metrics") or {}
            simulated = what_if_result.get("simulated_metrics") or {}
            baseline_score = _safe_float(
                baseline.get("avg_review_score")
                or what_if_result.get("current_avg_score")
            )
            simulated_score = _safe_float(
                simulated.get("avg_review_score")
                or what_if_result.get("simulated_avg_score")
            )
            if baseline_score is not None and simulated_score is not None:
                signals.append(
                    DecisionSignal(
                        domain="seller",
                        signal="what-if seller removal uplift",
                        value=simulated_score,
                        benchmark=baseline_score,
                        severity_score=_cap_score(
                            abs(simulated_score - baseline_score) / 0.5 + 0.5
                        ),
                        evidence_text=summary_text
                        or f"What-if 显示剔除高差评卖家后评分可从 {baseline_score:.2f} 提升到 {simulated_score:.2f}。",
                        metadata=_metadata(
                            signal_family="what_if",
                            scenario_type=scenario_type,
                        ),
                    )
                )

    if visualization_result.get("summary_text"):
        source_summaries = {
            "analysis": str(analysis_result.get("summary_text") or ""),
            "nlp": str(nlp_result.get("summary_text") or ""),
            "forecast": str(forecast_result.get("summary_text") or ""),
            "visualization": str(visualization_result.get("summary_text") or ""),
        }
    else:
        source_summaries = {
            "analysis": str(analysis_result.get("summary_text") or ""),
            "nlp": str(nlp_result.get("summary_text") or ""),
            "forecast": str(forecast_result.get("summary_text") or ""),
        }

    return EvidenceBundle(
        query_goal=user_query or "未提供用户问题",
        business_scope=str(state.get("intent") or "general"),
        signals=signals,
        source_summaries=source_summaries,
    )
