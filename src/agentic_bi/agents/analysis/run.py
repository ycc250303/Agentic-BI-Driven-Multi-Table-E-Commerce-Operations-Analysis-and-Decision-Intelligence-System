"""数据分析 Agent 的依赖装配、公开调用和 CLI。"""

from __future__ import annotations

import argparse
from typing import cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from agentic_bi.agents.analysis.graph import (
    AnalysisContext,
    AnalysisInput,
    build_analysis_graph,
)
from agentic_bi.agents.analysis.schemas import AnalysisRequest, AnalysisResult
from agentic_bi.core.llm import ModelGateway
from agentic_bi.core.observability import build_run_config, configure_langsmith
from agentic_bi.core.settings import Settings
from agentic_bi.data.database import ReadOnlyDatabase
from agentic_bi.data.metrics import MetricCatalog
from agentic_bi.data.sql_guard import SqlGuard, load_sql_policy
from agentic_bi.data.store import Store


def create_analysis_context(settings: Settings) -> AnalysisContext:
    """构造一次进程可复用的 Analysis 运行依赖。"""
    metrics = MetricCatalog.load(settings.config_dir / "metrics.yaml")
    policy = load_sql_policy(settings.config_dir / "sql_policy.yaml")
    return AnalysisContext(
        settings=settings,
        models=ModelGateway(settings),
        metrics=metrics,
        sql_guard=SqlGuard(policy),
        database=ReadOnlyDatabase(settings),
        store=Store(settings.artifact_dir),
    )


def run_analysis(
    request: AnalysisRequest,
    *,
    settings: Settings | None = None,
    context: AnalysisContext | None = None,
    config: RunnableConfig | None = None,
) -> AnalysisResult:
    """同步执行一次数据分析任务。

    调用方传入 context 时，本函数不会关闭其中的数据库连接池；
    独立 CLI 未传 context 时，由本函数创建并释放连接池。
    """
    if settings is not None and context is not None:
        raise ValueError("settings 与 context 不能同时传入")

    owns_context = context is None
    active_settings = settings or (context.settings if context else Settings())
    configure_langsmith(active_settings)

    active_context = context or create_analysis_context(active_settings)
    active_config = config or build_run_config(
        run_name="analysis.run",
        tags=(
            "analysis",
            active_settings.environment,
            active_settings.llm_provider.value,
        ),
        metadata={
            "task_id": request.task_id,
            "agent": "analysis",
            "environment": active_settings.environment,
            "model_provider": active_settings.llm_provider.value,
            "model": active_settings.model_for(),
        },
        recursion_limit=20,
    )

    graph = build_analysis_graph()
    try:
        output = graph.invoke(
            AnalysisInput(request=request),
            context=active_context,
            config=active_config,
        )
        return cast(AnalysisResult, output["result"])
    finally:
        if owns_context:
            active_context.database.close()


def main() -> None:
    """运行 Analysis CLI。"""
    parser = argparse.ArgumentParser(description="运行数据分析 Agent")
    parser.add_argument("question", help="自包含的单一数据分析问题")
    parser.add_argument(
        "--task-id",
        default=None,
        help="可选任务标识；默认自动生成",
    )
    parser.add_argument(
        "--locale",
        default="zh-CN",
        help="摘要语言区域，默认 zh-CN",
    )
    arguments = parser.parse_args()

    request = AnalysisRequest(
        task_id=arguments.task_id or f"analysis-{uuid4().hex}",
        question=arguments.question,
        locale=arguments.locale,
    )
    result = run_analysis(request)
    print(result.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True))


if __name__ == "__main__":
    main()
