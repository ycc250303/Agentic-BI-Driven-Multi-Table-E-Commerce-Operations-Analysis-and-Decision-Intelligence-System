from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentic_bi.agents.analysis.schemas import (
    AnalysisClaim,
    AnalysisOutput,
    AnalysisSemanticSpec,
    FilterOperator,
    FilterSpec,
    TimeRange,
)
from agentic_bi.core.models import EvidenceEnvelope


def test_between_requires_two_values() -> None:
    with pytest.raises(ValidationError, match="恰好包含两个元素"):
        FilterSpec(
            field="purchase_date",
            operator=FilterOperator.BETWEEN,
            value=["2026-01-01"],
        )


def test_time_range_is_left_closed_right_open() -> None:
    moment = datetime(2026, 1, 1, tzinfo=UTC)

    with pytest.raises(ValidationError, match="start 必须早于"):
        TimeRange(start=moment, end=moment)


def test_sort_direction_requires_sort_field() -> None:
    with pytest.raises(ValidationError, match="必须设置 sort_by"):
        AnalysisSemanticSpec(metric_ids=("revenue",), sort_direction="desc")


def test_claim_must_reference_existing_evidence() -> None:
    evidence = EvidenceEnvelope(
        evidence_id="ev-1",
        metric_ids=("revenue",),
        columns=("revenue",),
        preview=({"revenue": 10.5},),
        row_count=1,
        source_tables=("order_items",),
        data_snapshot="olist-local-v1",
        executed_at=datetime(2026, 10, 13, tzinfo=UTC),
        execution_time_ms=10,
    )

    with pytest.raises(ValidationError, match="不存在的 evidence_id"):
        AnalysisOutput(
            task_id="task-1",
            evidences=(evidence,),
            claims=(AnalysisClaim(evidence_id="ev-missing", text="销售额为 10.5"),),
        )
