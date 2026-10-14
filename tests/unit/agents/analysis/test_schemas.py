from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from agentic_bi.agents.analysis.schemas import (
    AnalysisClaim,
    AnalysisOutput,
    AnalysisRequest,
    AnalysisSemanticSpec,
    FilterOperator,
    FilterSpec,
    TimeRange,
)
from agentic_bi.core.models import EvidenceEnvelope


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
            sort_direction="desc",
        )


def test_request_accepts_question_without_semantic_spec() -> None:
    request = AnalysisRequest(
        task_id="task-1",
        question="2017 年哪个州的销售额最高？",
    )

    assert request.semantic_spec is None
    assert request.locale == "zh-CN"


def test_ambiguity_schema_uses_a_genuine_missing_business_definition() -> None:
    property_schema = AnalysisSemanticSpec.model_json_schema()["properties"]["ambiguities"]
    description = property_schema["description"]

    assert "哪个表现最好" in description
    assert "销售额”究竟是否包含运费" not in description


def test_claim_must_reference_existing_evidence() -> None:
    evidence = EvidenceEnvelope(
        evidence_id="ev-1",
        metric_ids=("total_gmv",),
        columns=("total_gmv",),
        preview=({"total_gmv": 10.5},),
        row_count=1,
        source_views=("mv_monthly_sales",),
        data_snapshot="orders:99441:2018-10-17T17:30:18",
        executed_at=datetime(2026, 10, 14, tzinfo=UTC),
        execution_time_ms=10,
    )

    with pytest.raises(ValidationError, match="不存在的 evidence_id"):
        AnalysisOutput(
            task_id="task-1",
            evidences=(evidence,),
            claims=(
                AnalysisClaim(
                    evidence_id="ev-missing",
                    text="销售额为 10.5 BRL",
                ),
            ),
        )
