from langchain_core.messages import HumanMessage
from langchain_core.tracers.langchain import wait_for_all_tracers
from langsmith import Client

from agentic_bi.core.observability import build_run_config, configure_langsmith
from agentic_bi.core.settings import Settings

settings = Settings()
configure_langsmith(settings)

from agentic_bi.core.llm import ModelGateway

gateway = ModelGateway(settings)
gateway.invoke(
    [HumanMessage(content="只回复一个词：pong")],
    config=build_run_config(
        run_name="observability-smoke",
        tags=("component:core", "env:dev"),
        metadata={"suite": "manual"},
    ),
)
wait_for_all_tracers()

runs = list(
    Client().list_runs(
        project_name=settings.langsmith_project,
        filter='eq(name, "observability-smoke")',
        limit=5,
    )
)
print(len(runs), runs[0].url if runs else "没有 run")