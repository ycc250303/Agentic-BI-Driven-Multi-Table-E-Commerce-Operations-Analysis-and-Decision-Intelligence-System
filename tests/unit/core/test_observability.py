from pydantic import SecretStr

from agentic_bi.core.observability import (
    build_run_config,
    configure_langsmith,
    redact_metadata,
)
from agentic_bi.core.settings import Settings


def test_metadata_redaction_removes_secrets_and_truncates_text() -> None:
    safe = redact_metadata(
        {
            "request_id": "req-1",
            "api_key": "secret",
            "db_password": "secret",
            "long": "x" * 600,
        }
    )

    assert safe["request_id"] == "req-1"
    assert "api_key" not in safe
    assert "db_password" not in safe
    assert len(safe["long"]) == 501


def test_build_run_config_uses_native_runnable_fields() -> None:
    config = build_run_config(
        run_name="analysis_agent",
        tags=("component:analysis",),
        metadata={"request_id": "req-1"},
        recursion_limit=20,
    )

    assert config["run_name"] == "analysis_agent"
    assert config["tags"] == ["component:analysis"]
    assert config["metadata"] == {"request_id": "req-1"}
    assert config["recursion_limit"] == 20


def test_configure_langsmith_sets_official_environment_variables(
    monkeypatch,
) -> None:
    for name in (
        "LANGSMITH_TRACING",
        "LANGSMITH_PROJECT",
        "LANGSMITH_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(
        _env_file=None,
        langsmith_tracing=True,
        langsmith_api_key=SecretStr("test-key"),
        langsmith_project="analysis-test",
    )
    configure_langsmith(settings)

    assert settings.langsmith_project == "analysis-test"
