from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentic_bi.core.models import (
    AgentResult,
    AgentStatus,
    ErrorCode,
    ErrorInfo,
    EvidenceEnvelope,
    EvidenceSource,
)


def test_success_result_requires_value() -> None:
    with pytest.raises(ValidationError, match="success 状态必须包含 value"):
        AgentResult[str](status=AgentStatus.SUCCESS)


def test_failed_result_requires_error() -> None:
    with pytest.raises(ValidationError, match="failed 状态必须包含 error"):
        AgentResult[str](status=AgentStatus.FAILED)


def test_error_does_not_accept_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ErrorInfo(
            code=ErrorCode.INTERNAL_ERROR,
            stage="test",
            message="safe",
            stack="secret stack",  # type: ignore[call-arg]
        )


def test_evidence_round_trip_is_json_safe() -> None:
    evidence = EvidenceEnvelope(
        evidence_id="ev-1",
        metric_ids=("revenue",),
        columns=("revenue",),
        preview=({"revenue": 10.5},),
        returned_row_count=1,
        sources=(EvidenceSource(name="order_items", kind="table"),),
        data_snapshot="olist-local-v1",
        executed_at=datetime(2026, 10, 13, tzinfo=UTC),
    )

    restored = EvidenceEnvelope.model_validate_json(evidence.model_dump_json())

    assert restored == evidence
