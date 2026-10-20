from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from agentic_bi.agents.analysis import graph as analysis_graph
from agentic_bi.agents.analysis.graph import (
    AnalysisContext,
    AnalysisInput,
    build_analysis_graph,
)
from agentic_bi.agents.analysis.schemas import (
    AnalysisClaim,
    AnalysisClarification,
    AnalysisInterpretation,
    AnalysisRequest,
    AnalysisSemanticSpec,
    ClarificationCode,
    OutputMode,
    SqlDraft,
    SummaryDraft,
)
from agentic_bi.core.llm import ModelGateway
from agentic_bi.core.models import AgentStatus, ErrorCode
from agentic_bi.core.settings import Settings
from agentic_bi.data.database import QueryExecution, QueryPlan, ReadOnlyDatabase
from agentic_bi.data.metrics import MetricCatalog
from agentic_bi.data.sql_guard import SqlGuard, load_sql_policy
from agentic_bi.data.store import Store

CONFIG_PATH = Path("config")


class _DatabaseStub:
    def explain(self, sql: str) -> QueryPlan:
        assert "MV_STATE_SALES" in sql.upper()
        return QueryPlan(estimated_rows=None)

    def execute(self, sql: str) -> QueryExecution:
        assert "LIMIT 5001" in sql.upper()
        return QueryExecution(
            columns=("customer_state", "total_gmv"),
            rows=({"customer_state": "SP", "total_gmv": 123.45},),
            returned_row_count=1,
            truncated=True,
            data_snapshot="orders:99441:2018-10-17T17:30:18",
        )


def _context(tmp_path: Path) -> AnalysisContext:
    settings = Settings(
        config_dir=CONFIG_PATH,
        artifact_dir=tmp_path,
        sql_max_rows=5000,
        sql_max_repair_attempts=2,
        evidence_preview_rows=20,
    )
    return AnalysisContext(
        settings=settings,
        models=cast(ModelGateway, object()),
        metrics=MetricCatalog.load(CONFIG_PATH / "metrics.yaml"),
        sql_guard=SqlGuard(load_sql_policy(CONFIG_PATH / "sql_policy.yaml")),
        database=cast(ReadOnlyDatabase, _DatabaseStub()),
        store=Store(tmp_path),
    )


def _semantic_spec() -> AnalysisSemanticSpec:
    return AnalysisSemanticSpec(
        metric_ids=("total_gmv",),
        dimensions=("customer_state",),
        operation=OutputMode.RANKING,
        sort_by="total_gmv",
        sort_direction="desc",
        limit=1,
    )


def test_success_path_returns_one_evidence_and_projects_summary_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    summary_evidence: dict[str, Any] = {}

    def invoke_stub(
        _runtime: Any,
        *,
        prompt_name: str,
        variables: dict[str, Any],
        schema: type[Any],
        run_name: str,
    ) -> Any:
        assert run_name.startswith("analysis.")
        if prompt_name == "analysis/generate_sql":
            assert schema is SqlDraft
            return SqlDraft(
                sql=("SELECT customer_state, total_gmv FROM mv_state_sales ORDER BY total_gmv DESC")
            )

        assert prompt_name == "analysis/summarize"
        assert schema is SummaryDraft
        summary_evidence.update(json.loads(variables["evidence"]))
        evidence_id = summary_evidence["evidence_id"]
        return SummaryDraft(
            headline="SP 州的 GMV 最高，为 123.45 BRL。",
            claims=(
                AnalysisClaim(
                    evidence_id=evidence_id,
                    text="SP 州的 GMV 为 123.45 BRL。",
                ),
            ),
            limitations=("结果受当前数据覆盖范围限制。",),
        )

    monkeypatch.setattr(analysis_graph, "_invoke", invoke_stub)
    compiled = build_analysis_graph()
    request = AnalysisRequest(
        task_id="task-success",
        question="哪个客户州的 GMV 最高？",
        semantic_spec=_semantic_spec(),
    )

    output = compiled.invoke(
        AnalysisInput(request=request),
        context=_context(tmp_path),
    )
    result = output["result"]

    assert result.status == AgentStatus.SUCCESS
    assert result.value is not None
    assert result.value.clarification is None
    assert result.value.evidence is not None
    assert result.value.evidence.grain == ("customer_state",)
    assert result.value.evidence.returned_row_count == 1
    assert result.value.evidence.sources[0].name == "mv_state_sales"
    assert result.value.evidence.sources[0].kind == "view"
    assert result.value.evidence.truncated is True
    assert result.value.evidence.warnings == ("EXPLAIN 未返回可识别的扫描行数估算。",)
    assert result.value.limitations == ("结果受当前数据覆盖范围限制。",)
    assert result.warnings == ()

    assert set(summary_evidence) == {
        "columns",
        "evidence_id",
        "grain",
        "metric_ids",
        "preview",
        "returned_row_count",
        "scope",
        "truncated",
        "units",
        "warnings",
    }


def test_clarification_without_metric_returns_needs_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    question = "请问你希望按 GMV、订单量还是准时率评价表现？"

    def invoke_stub(
        _runtime: Any,
        *,
        prompt_name: str,
        variables: dict[str, Any],
        schema: type[Any],
        run_name: str,
    ) -> AnalysisInterpretation:
        assert prompt_name == "analysis/interpret"
        assert variables["question"] == "哪个客户州表现最好？"
        assert schema is AnalysisInterpretation
        assert run_name == "analysis.interpret"
        return AnalysisInterpretation(
            interpretation=AnalysisClarification(
                code=ClarificationCode.MISSING_METRIC,
                questions=(question,),
            )
        )

    monkeypatch.setattr(analysis_graph, "_invoke", invoke_stub)
    request = AnalysisRequest(
        task_id="task-needs-input",
        question="哪个客户州表现最好？",
    )

    output = build_analysis_graph().invoke(
        AnalysisInput(request=request),
        context=_context(tmp_path),
    )
    result = output["result"]

    assert result.status == AgentStatus.NEEDS_INPUT
    assert result.value is not None
    assert result.value.clarification is not None
    assert result.value.clarification.code == ClarificationCode.MISSING_METRIC
    assert result.value.clarification.questions == (question,)
    assert result.value.evidence is None
    assert result.value.headline is None


def test_clarification_does_not_enter_catalog_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    question = "要按卖家还是按客户州查看平均配送天数？"

    def invoke_stub(
        _runtime: Any,
        **_kwargs: Any,
    ) -> AnalysisInterpretation:
        return AnalysisInterpretation(
            interpretation=AnalysisClarification(
                code=ClarificationCode.INCOMPATIBLE_DIMENSIONS,
                questions=(question,),
            )
        )

    monkeypatch.setattr(analysis_graph, "_invoke", invoke_stub)
    request = AnalysisRequest(
        task_id="task-clarify-unsupported-dimension",
        question="各卖家的平均配送天数是多少？",
    )

    output = build_analysis_graph().invoke(
        AnalysisInput(request=request),
        context=_context(tmp_path),
    )
    result = output["result"]

    assert result.status == AgentStatus.NEEDS_INPUT
    assert result.value is not None
    assert result.value.clarification is not None
    assert result.value.clarification.code == ClarificationCode.INCOMPATIBLE_DIMENSIONS
    assert result.value.clarification.questions == (question,)
    assert result.error is None


def test_unsupported_dimension_fails_without_clarification(tmp_path: Path) -> None:
    request = AnalysisRequest(
        task_id="task-invalid-dimension",
        question="各卖家的平均配送天数是多少？",
        semantic_spec=AnalysisSemanticSpec(
            metric_ids=("avg_delivery_days",),
            dimensions=("seller_id",),
            operation=OutputMode.TABLE,
        ),
    )

    output = build_analysis_graph().invoke(
        AnalysisInput(request=request),
        context=_context(tmp_path),
    )
    result = output["result"]

    assert result.status == AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == ErrorCode.STRUCTURED_OUTPUT_INVALID


def test_retry_command_returns_to_sql_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repair_feedback: list[str] = []

    def invoke_stub(
        _runtime: Any,
        *,
        prompt_name: str,
        variables: dict[str, Any],
        schema: type[Any],
        run_name: str,
    ) -> Any:
        assert run_name.startswith("analysis.")
        if prompt_name == "analysis/generate_sql":
            assert schema is SqlDraft
            repair_feedback.append(cast(str, variables["repair_feedback"]))
            if len(repair_feedback) == 1:
                return SqlDraft(sql="SELECT 1 AS total_gmv")
            return SqlDraft(
                sql=("SELECT customer_state, total_gmv FROM mv_state_sales ORDER BY total_gmv DESC")
            )

        assert prompt_name == "analysis/summarize"
        assert schema is SummaryDraft
        return SummaryDraft(headline="SP 州的 GMV 最高，为 123.45 BRL。")

    monkeypatch.setattr(analysis_graph, "_invoke", invoke_stub)
    request = AnalysisRequest(
        task_id="task-repair",
        question="哪个客户州的 GMV 最高？",
        semantic_spec=_semantic_spec(),
    )

    output = build_analysis_graph().invoke(
        AnalysisInput(request=request),
        context=_context(tmp_path),
    )

    assert output["result"].status == AgentStatus.SUCCESS
    assert repair_feedback[0] == "首次生成，无反馈。"
    assert "第 1 次校验失败" in repair_feedback[1]


def test_repeated_repair_sql_stops_before_second_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    generated_sql: list[str] = []

    def invoke_stub(
        _runtime: Any,
        *,
        prompt_name: str,
        variables: dict[str, Any],
        schema: type[Any],
        run_name: str,
    ) -> SqlDraft:
        assert prompt_name == "analysis/generate_sql"
        assert schema is SqlDraft
        assert run_name == "analysis.generate_sql"
        generated_sql.append(cast(str, variables["repair_feedback"]))
        if len(generated_sql) == 1:
            return SqlDraft(sql="SELECT 1 AS total_gmv")
        return SqlDraft(sql="select 1 as total_gmv /* unchanged */")

    monkeypatch.setattr(analysis_graph, "_invoke", invoke_stub)
    request = AnalysisRequest(
        task_id="task-repeated-repair",
        question="哪个客户州的 GMV 最高？",
        semantic_spec=_semantic_spec(),
    )

    output = build_analysis_graph().invoke(
        AnalysisInput(request=request),
        context=_context(tmp_path),
    )
    result = output["result"]

    assert result.status == AgentStatus.FAILED
    assert result.error is not None
    assert result.error.code == ErrorCode.SQL_POLICY_BLOCKED
    assert result.error.stage == "generate_sql"
    assert result.error.context == {
        "repair_attempts": 1,
        "maximum_repair_attempts": 2,
        "reason": "repeated_sql",
    }
    assert len(generated_sql) == 2
    assert "error_code=missing_source" in generated_sql[1]
