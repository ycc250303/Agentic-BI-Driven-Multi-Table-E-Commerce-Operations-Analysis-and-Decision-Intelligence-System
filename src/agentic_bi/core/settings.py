"""集中读取环境变量，不在 Agent 节点中散落配置访问。"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelProvider(StrEnum):
    DEEPSEEK = "deepseek"
    QWEN = "qwen"


class Settings(BaseSettings):
    """新核心第一阶段真正使用的配置。

    数据库和 SQL 预算字段在 ``data`` 纵切落地时再加入，避免先为尚未存在的
    模块维护配置对象。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        case_sensitive=False,
    )

    environment: Literal["dev", "test", "staging", "prod"] = Field(
        default="dev",
        validation_alias="AGENTIC_BI_ENV",
    )
    config_dir: Path = Field(
        default=Path("config"),
        validation_alias="AGENTIC_BI_CONFIG_DIR",
    )
    artifact_dir: Path = Field(
        default=Path("runtime/artifacts"),
        validation_alias="AGENTIC_BI_ARTIFACT_DIR",
    )

    llm_provider: ModelProvider = Field(
        default=ModelProvider.DEEPSEEK,
        validation_alias="AGENTIC_BI_LLM_PROVIDER",
    )
    deepseek_model: str = Field(
        default="deepseek-v4-flash",
        min_length=1,
        validation_alias="AGENTIC_BI_DEEPSEEK_MODEL",
    )
    qwen_model: str = Field(
        default="qwen3.8-max",
        min_length=1,
        validation_alias="AGENTIC_BI_QWEN_MODEL",
    )
    llm_timeout_seconds: float = Field(
        default=60,
        gt=0,
        le=300,
        validation_alias="AGENTIC_BI_LLM_TIMEOUT",
    )
    llm_max_retries: int = Field(
        default=1,
        ge=0,
        le=3,
        validation_alias="AGENTIC_BI_LLM_MAX_RETRIES",
    )
    llm_thinking_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "AGENTIC_BI_LLM_THINKING_ENABLED",
            "DEEPSEEK_THINKING_ENABLED",
        ),
    )

    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="DEEPSEEK_API_KEY",
        repr=False,
    )
    dashscope_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="DASHSCOPE_API_KEY",
        repr=False,
    )
    dashscope_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("https://dashscope.aliyuncs.com/compatible-mode/v1"),
        validation_alias="DASHSCOPE_BASE_URL",
    )

    langsmith_tracing: bool = Field(
        default=False,
        validation_alias="LANGSMITH_TRACING",
    )
    langsmith_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="LANGSMITH_API_KEY",
        repr=False,
    )
    langsmith_project: str = Field(
        default="agentic-bi",
        min_length=1,
        validation_alias="LANGSMITH_PROJECT",
    )
    langsmith_workspace_id: str | None = Field(
        default=None,
        validation_alias="LANGSMITH_WORKSPACE_ID",
    )
    langsmith_endpoint: AnyHttpUrl | None = Field(
        default=None,
        validation_alias="LANGSMITH_ENDPOINT",
    )

    @model_validator(mode="after")
    def validate_langsmith(self) -> Settings:
        """启用 tracing 时要求 LangSmith API Key 已配置。

        输入：
        - ``langsmith_tracing``：是否启用追踪
        - ``langsmith_api_key``：LangSmith API Key

        输出：
        - 同一 ``Settings``：tracing 开启且 Key 为空时抛 ``ValueError``
        """
        if self.langsmith_tracing and self.langsmith_api_key is None:
            raise ValueError("启用 LangSmith tracing 时必须设置 LANGSMITH_API_KEY")
        return self

    def model_for(self, provider: ModelProvider | None = None) -> str:
        """返回指定提供商配置的模型名。

        输入：
        - ``provider``：为空时使用 ``llm_provider``

        输出：
        - DeepSeek：``deepseek_model``
        - 通义千问：``qwen_model``
        """
        selected = provider or self.llm_provider
        if selected == ModelProvider.DEEPSEEK:
            return self.deepseek_model
        return self.qwen_model

    def api_key_for(self, provider: ModelProvider | None = None) -> SecretStr:
        """返回指定提供商的 API Key。

        输入：
        - ``provider``：为空时使用 ``llm_provider``

        输出：
        - ``SecretStr``：Key 缺失或为空时抛 ``ValueError``，消息只含环境变量名
        """
        selected = provider or self.llm_provider
        key = (
            self.deepseek_api_key if selected == ModelProvider.DEEPSEEK else self.dashscope_api_key
        )
        if key is None or not key.get_secret_value():
            variable = (
                "DEEPSEEK_API_KEY" if selected == ModelProvider.DEEPSEEK else "DASHSCOPE_API_KEY"
            )
            raise ValueError(f"使用 {selected.value} 时必须设置 {variable}")
        return key
