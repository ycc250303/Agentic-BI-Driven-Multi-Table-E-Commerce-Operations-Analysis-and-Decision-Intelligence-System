from __future__ import annotations

from typing import Any

from .schemas import DecisionTheme, EvidenceBundle, ScoredProblem


DELIVERY_ON_TIME_THRESHOLD = 0.82
DELIVERY_DAYS_THRESHOLD = 8.0
NEGATIVE_TOPIC_SHARE_THRESHOLD = 0.2
LOW_REVIEW_THRESHOLD = 3.6
CATEGORY_NEGATIVE_RATE_THRESHOLD = 0.25
REGION_NEGATIVE_RATE_THRESHOLD = 0.22


def _severity_from_score(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _priority_score(impact: float, urgency: float, feasibility: float) -> float:
    return round(0.5 * impact + 0.3 * urgency + 0.2 * feasibility, 4)


def _problem(
    *,
    problem_type: str,
    decision_theme: DecisionTheme,
    problem: str,
    evidence: list[str],
    impact: float,
    urgency: float,
    feasibility: float,
    root_causes: list[str],
    metadata: dict[str, Any] | None = None,
) -> ScoredProblem:
    priority = _priority_score(impact, urgency, feasibility)
    return ScoredProblem(
        problem_type=problem_type,
        decision_theme=decision_theme,
        problem=problem,
        evidence=evidence,
        severity=_severity_from_score(priority),
        impact_score=impact,
        urgency_score=urgency,
        feasibility_score=feasibility,
        priority_score=priority,
        root_cause_candidates=root_causes,
        metadata=metadata or {},
    )


def detect_problems_and_score(bundle: EvidenceBundle) -> list[ScoredProblem]:
    problems: list[ScoredProblem] = []
    delivery_signals = [s for s in bundle.signals if s.domain == "delivery"]
    seller_signals = [s for s in bundle.signals if s.domain == "seller"]
    category_signals = [s for s in bundle.signals if s.domain == "category"]
    region_signals = [s for s in bundle.signals if s.domain == "region"]
    forecast_signals = [s for s in bundle.signals if s.domain == "forecast"]

    late_rate_signal = next(
        (s for s in delivery_signals if "on_time_rate" in s.signal), None
    )
    delivery_delay_signal = next(
        (
            s
            for s in delivery_signals
            if "avg_delivery_days" in s.signal or "delayed_orders" in s.signal
        ),
        None,
    )
    delivery_nlp_signal = next(
        (s for s in delivery_signals if "delivery_delay topic share" in s.signal), None
    )
    if late_rate_signal or delivery_delay_signal or delivery_nlp_signal:
        impact = max(
            [s.severity_score for s in (late_rate_signal, delivery_delay_signal, delivery_nlp_signal) if s],
            default=0.0,
        )
        if impact >= 0.45:
            evidence = [
                s.evidence_text
                for s in (late_rate_signal, delivery_delay_signal, delivery_nlp_signal)
                if s
            ]
            problems.append(
                _problem(
                    problem_type="delivery",
                    decision_theme="物流优化",
                    problem="区域履约表现不佳，配送延迟正在侵蚀客户体验。",
                    evidence=evidence,
                    impact=impact,
                    urgency=min(1.0, impact + 0.08),
                    feasibility=0.72,
                    root_causes=[
                        "部分区域仓配路径或物流资源不足。",
                        "高延迟卖家的发货及时性和履约能力偏弱。",
                        "客户负面评论已集中指向配送延迟问题。",
                    ],
                )
            )

    seller_low_review = next(
        (s for s in seller_signals if "avg_review_score below threshold" in s.signal),
        None,
    )
    seller_what_if = next(
        (s for s in seller_signals if "what-if seller removal uplift" in s.signal), None
    )
    if seller_low_review or seller_what_if:
        impact = max(
            [s.severity_score for s in (seller_low_review, seller_what_if) if s],
            default=0.0,
        )
        if impact >= 0.45:
            evidence = [
                s.evidence_text for s in (seller_low_review, seller_what_if) if s
            ]
            problems.append(
                _problem(
                    problem_type="seller",
                    decision_theme="卖家治理",
                    problem="低质量卖家正在拉低整体评分并增加售后风险。",
                    evidence=evidence,
                    impact=impact,
                    urgency=min(1.0, impact + 0.06),
                    feasibility=0.8,
                    root_causes=[
                        "少数卖家评分显著偏低且投诉集中。",
                        "当前缺少针对高风险卖家的分层治理机制。",
                        "What-if 结果显示剔除高差评卖家后平台指标存在改善空间。",
                    ],
                )
            )

    category_sales_signal = next(
        (
            s
            for s in category_signals
            if "sales decline" in s.signal or "bad_review_count" in s.signal
        ),
        None,
    )
    category_quality_signal = next(
        (s for s in category_signals if "negative quality rate" in s.signal), None
    )
    if category_sales_signal or category_quality_signal:
        impact = max(
            [s.severity_score for s in (category_sales_signal, category_quality_signal) if s],
            default=0.0,
        )
        if impact >= 0.45:
            evidence = [
                s.evidence_text
                for s in (category_sales_signal, category_quality_signal)
                if s
            ]
            problems.append(
                _problem(
                    problem_type="category",
                    decision_theme="品类治理",
                    problem="问题品类同时出现销售承压与质量负面反馈聚集。",
                    evidence=evidence,
                    impact=impact,
                    urgency=min(1.0, impact + 0.04),
                    feasibility=0.7,
                    root_causes=[
                        "问题品类 SKU 质量控制不足或商品信息表达不准确。",
                        "差评主题集中在质量、缺件或货不对板。",
                    ],
                )
            )

    region_sales_signal = next(
        (s for s in region_signals if "high gmv with high negative rate" in s.signal),
        None,
    )
    region_sentiment_signal = next(
        (s for s in region_signals if "regional negative sentiment" in s.signal), None
    )
    if region_sales_signal or region_sentiment_signal:
        impact = max(
            [s.severity_score for s in (region_sales_signal, region_sentiment_signal) if s],
            default=0.0,
        )
        if impact >= 0.45:
            evidence = [
                s.evidence_text
                for s in (region_sales_signal, region_sentiment_signal)
                if s
            ]
            problems.append(
                _problem(
                    problem_type="region",
                    decision_theme="区域运营",
                    problem="重点区域虽有销售贡献，但体验指标偏弱，存在口碑透支风险。",
                    evidence=evidence,
                    impact=impact,
                    urgency=min(1.0, impact + 0.05),
                    feasibility=0.68,
                    root_causes=[
                        "区域履约承诺与实际体验存在偏差。",
                        "当地客服补偿、承诺管理或品类供给结构不匹配。",
                    ],
                )
            )

    forecast_trend_signal = next(
        (s for s in forecast_signals if "growth slowdown" in s.signal), None
    )
    if forecast_trend_signal and forecast_trend_signal.severity_score >= 0.45:
        problems.append(
            _problem(
                problem_type="forecast",
                decision_theme="综合运营",
                problem="未来增长放缓风险已显现，需要提前准备保增长动作。",
                evidence=[forecast_trend_signal.evidence_text],
                impact=forecast_trend_signal.severity_score,
                urgency=min(1.0, forecast_trend_signal.severity_score + 0.05),
                feasibility=0.5,
                root_causes=[
                    "预测结果显示短期销售趋势走平或放缓。",
                    "若当前履约、口碑或品类问题不处理，增长压力会进一步放大。",
                ],
            )
        )

    if not problems:
        problems.append(
            _problem(
                problem_type="general",
                decision_theme="综合运营",
                problem="当前未识别出高置信度单点风险，建议继续监控核心经营指标。",
                evidence=["上游结构化信号中未出现明显超阈值异常。"],
                impact=0.2,
                urgency=0.2,
                feasibility=0.9,
                root_causes=["当前输入更偏向常规经营总结，而非单一高风险诊断场景。"],
            )
        )

    return sorted(problems, key=lambda item: item.priority_score, reverse=True)
