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
