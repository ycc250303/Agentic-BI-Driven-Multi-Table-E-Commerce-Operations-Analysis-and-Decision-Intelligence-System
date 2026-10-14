import pytest
from pydantic import SecretStr, ValidationError

from agentic_bi.core.settings import ModelProvider, Settings


def test_settings_support_field_names_without_env_file() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider=ModelProvider.QWEN,
        qwen_model="qwen-test",
        dashscope_api_key=SecretStr("secret"),
    )

    assert settings.model_for() == "qwen-test"
    assert settings.api_key_for().get_secret_value() == "secret"


def test_api_key_is_loaded_lazily() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider=ModelProvider.DEEPSEEK,
        deepseek_api_key=None,
    )

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        settings.api_key_for()


def test_blank_optional_langsmith_values_are_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "")
    monkeypatch.setenv("LANGSMITH_WORKSPACE_ID", "")
    monkeypatch.setenv("LANGSMITH_API_KEY", "")

    settings = Settings(_env_file=None)

    assert settings.langsmith_endpoint is None
    assert settings.langsmith_workspace_id is None
    assert settings.langsmith_api_key is None


def test_langsmith_tracing_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="LANGSMITH_API_KEY"):
        Settings(
            _env_file=None,
            langsmith_tracing=True,
            langsmith_api_key=None,
        )


def test_secrets_are_not_exposed_in_repr() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key=SecretStr("never-print-me"),
    )

    assert "never-print-me" not in repr(settings)


def test_readonly_database_does_not_fallback_to_writer_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENTIC_BI_DB_READONLY_USER", raising=False)
    monkeypatch.delenv("AGENTIC_BI_DB_READONLY_PASSWORD", raising=False)
    monkeypatch.setenv("AGENTIC_BI_DB_USER", "writer")
    monkeypatch.setenv("AGENTIC_BI_DB_PASSWORD", "writer-password")

    settings = Settings(_env_file=None)

    with pytest.raises(ValueError, match="READONLY_USER"):
        settings.readonly_credentials()


def test_readonly_credentials_are_available_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_BI_DB_READONLY_USER", "agent_reader")
    monkeypatch.setenv(
        "AGENTIC_BI_DB_READONLY_PASSWORD",
        "readonly-password",
    )

    settings = Settings(_env_file=None)
    user, password = settings.readonly_credentials()

    assert user == "agent_reader"
    assert password.get_secret_value() == "readonly-password"
