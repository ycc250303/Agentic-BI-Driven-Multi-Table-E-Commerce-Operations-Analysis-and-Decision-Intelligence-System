from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from agentic_bi.agents.analysis.schemas import (
    AnalysisClaim,
    AnalysisClarification,
    AnalysisInterpretation,
    AnalysisOutput,
    AnalysisRequest,
    AnalysisSemanticSpec,
    ClarificationCode,
    FilterOperator,
    FilterSpec,
    OutputMode,
    TimeRange,
)
from agentic_bi.core.models import EvidenceEnvelope, EvidenceSource


def test_between_requires_two_values() -> None:
    with pytest.raises(ValidationError, match="恰好包含两个元素"):
        FilterSpec(
            field="sales_month",
            operator=FilterOperator.BETWEEN,
            value=["2017-01"],
        )


def test_null_operator_rejects_value() -> None:
    with pytest.raises(ValidationError, match="不接受 value"):
        FilterSpec(
            field="customer_state",
            operator=FilterOperator.IS_NULL,
            value="SP",
        )


def test_time_range_is_left_closed_right_open() -> None:
    moment = date(2017, 1, 1)

    with pytest.raises(ValidationError, match="start 必须早于"):
        TimeRange(start=moment, end=moment)


def test_sort_direction_requires_sort_field() -> None:
    with pytest.raises(ValidationError, match="必须设置 sort_by"):
        AnalysisSemanticSpec(
            metric_ids=("total_gmv",),
            operation=OutputMode.RANKING,
            sort_direction="desc",
        )


def test_operation_requires_a_concrete_output_mode() -> None:
    with pytest.raises(ValidationError, match="operation"):
        AnalysisSemanticSpec(metric_ids=("total_gmv",))

    assert {mode.value for mode in OutputMode} == {
        "scalar",
        "table",
        "ranking",
        "trend",
        "distribution",
    }


def test_request_accepts_question_without_semantic_spec() -> None:
    request = AnalysisRequest(
        task_id="task-1",
        question="2017 年哪个州的销售额最高？",
    )

    assert request.semantic_spec is None
    assert request.locale == "zh-CN"


def test_clarification_does_not_require_an_executable_metric() -> None:
    result = AnalysisInterpretation.model_validate(
        {
            "interpretation": {
                "kind": "clarify",
                "code": "missing_metric",
                "questions": ["请说明用哪个指标衡量表现。"],
            }
        }
    )

    assert isinstance(result.interpretation, AnalysisClarification)
    assert result.interpretation.code == ClarificationCode.MISSING_METRIC


def test_executable_intent_still_requires_a_metric() -> None:
    with pytest.raises(ValidationError, match="metric_ids"):
        AnalysisInterpretation.model_validate(
            {
                "interpretation": {
                    "kind": "execute",
                    "metric_ids": [],
                    "operation": "ranking",
                }
            }
        )


def test_claim_must_reference_existing_evidence() -> None:
    evidence = EvidenceEnvelope(
        evidence_id="ev-1",
        metric_ids=("total_gmv",),
        columns=("total_gmv",),
        preview=({"total_gmv": 10.5},),
        returned_row_count=1,
        sources=(EvidenceSource(name="mv_monthly_sales", kind="view"),),
        data_snapshot="orders:99441:2018-10-17T17:30:18",
        executed_at=datetime(2026, 10, 14, tzinfo=UTC),
    )

    with pytest.raises(ValidationError, match="不存在的 evidence_id"):
        AnalysisOutput(
            task_id="task-1",
            evidence=evidence,
            claims=(
                AnalysisClaim(
                    evidence_id="ev-missing",
                    text="销售额为 10.5 BRL",
                ),
            ),
        )
