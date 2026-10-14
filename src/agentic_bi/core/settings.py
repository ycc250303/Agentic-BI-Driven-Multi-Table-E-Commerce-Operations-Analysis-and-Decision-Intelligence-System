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
    """应用、模型、只读数据库、SQL 预算与 LangSmith 配置。

    - environment：运行环境，取 dev、test、staging、prod
    - config_dir：配置目录
    - artifact_dir：Artifact 落盘目录
    - llm_provider：默认模型提供商
    - deepseek_model：DeepSeek 模型名
    - qwen_model：通义千问模型名
    - llm_timeout_seconds：客户端超时秒数
    - llm_max_retries：客户端瞬时重试次数
    - llm_thinking_enabled：是否开启 DeepSeek 思考
    - deepseek_api_key：DeepSeek API Key
    - dashscope_api_key：通义千问 API Key
    - dashscope_base_url：百炼 compatible-mode 地址
    - db_host：只读库主机
    - db_port：只读库端口
    - db_name：库名
    - db_readonly_user：只读账号
    - db_readonly_password：只读密码
    - db_pool_size：连接池大小
    - db_max_overflow：连接池允许的额外连接数
    - db_pool_recycle_seconds：连接回收秒数
    - db_connect_timeout_seconds：建连超时秒数
    - sql_timeout_ms：单条查询超时毫秒
    - sql_max_rows：结果行上限
    - sql_max_result_bytes：结果字节上限
    - sql_max_repair_attempts：SQL 修复次数上限
    - evidence_preview_rows：证据预览行数
    - langsmith_tracing：是否启用 LangSmith 追踪
    - langsmith_api_key：LangSmith API Key
    - langsmith_project：LangSmith 项目名
    - langsmith_workspace_id：LangSmith workspace，可空
    - langsmith_endpoint：LangSmith 区域端点，可空
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
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

    db_host: str = Field(
        default="127.0.0.1",
        min_length=1,
        validation_alias="AGENTIC_BI_DB_HOST",
    )
    db_port: int = Field(
        default=3306,
        ge=1,
        le=65535,
        validation_alias="AGENTIC_BI_DB_PORT",
    )
    db_name: str = Field(
        default="olist",
        min_length=1,
        validation_alias="AGENTIC_BI_DB_NAME",
    )
    db_readonly_user: str | None = Field(
        default=None,
        validation_alias="AGENTIC_BI_DB_READONLY_USER",
    )
    db_readonly_password: SecretStr | None = Field(
        default=None,
        validation_alias="AGENTIC_BI_DB_READONLY_PASSWORD",
        repr=False,
    )
    db_pool_size: int = Field(
        default=5,
        ge=1,
        le=50,
        validation_alias="AGENTIC_BI_DB_POOL_SIZE",
    )
    db_max_overflow: int = Field(
        default=5,
        ge=0,
        le=50,
        validation_alias="AGENTIC_BI_DB_MAX_OVERFLOW",
    )
    db_pool_recycle_seconds: int = Field(
        default=1800,
        ge=60,
        validation_alias="AGENTIC_BI_DB_POOL_RECYCLE_SECONDS",
    )
    db_connect_timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        validation_alias="AGENTIC_BI_DB_CONNECT_TIMEOUT_SECONDS",
    )

    sql_timeout_ms: int = Field(
        default=10_000,
        ge=100,
        le=120_000,
        validation_alias="AGENTIC_BI_SQL_TIMEOUT_MS",
    )
    sql_max_rows: int = Field(
        default=5_000,
        ge=1,
        le=50_000,
        validation_alias="AGENTIC_BI_SQL_MAX_ROWS",
    )
    sql_max_result_bytes: int = Field(
        default=10_485_760,
        ge=1024,
        validation_alias="AGENTIC_BI_SQL_MAX_RESULT_BYTES",
    )
    sql_max_repair_attempts: int = Field(
        default=2,
        ge=0,
        le=3,
        validation_alias="AGENTIC_BI_SQL_MAX_REPAIR_ATTEMPTS",
    )
    evidence_preview_rows: int = Field(
        default=20,
        ge=1,
        le=100,
        validation_alias="AGENTIC_BI_EVIDENCE_PREVIEW_ROWS",
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
        - langsmith_tracing：是否启用追踪
        - langsmith_api_key：LangSmith API Key

        输出：
        - 同一实例：tracing 开启且 Key 为空时抛 ``ValueError``
        """
        if self.langsmith_tracing and self.langsmith_api_key is None:
            raise ValueError("启用 LangSmith tracing 时必须设置 LANGSMITH_API_KEY")
        return self

    def model_for(self, provider: ModelProvider | None = None) -> str:
        """返回指定提供商配置的模型名。

        输入：
        - provider：为空时使用 llm_provider

        输出：
        - DeepSeek：deepseek_model
        - 通义千问：qwen_model
        """
        selected = provider or self.llm_provider
        if selected == ModelProvider.DEEPSEEK:
            return self.deepseek_model
        return self.qwen_model

    def api_key_for(self, provider: ModelProvider | None = None) -> SecretStr:
        """返回指定提供商的 API Key。

        输入：
        - provider：为空时使用 llm_provider

        输出：
        - API Key：缺失或为空时抛 ``ValueError``，消息只含环境变量名
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

    def readonly_credentials(self) -> tuple[str, SecretStr]:
        """返回在线查询只读账号，不允许回退维护账号。

        输入：
        - db_readonly_user：只读账号
        - db_readonly_password：只读密码

        输出：
        - 只读账号和密码：任一缺失时抛 ``ValueError``
        """

        user = (self.db_readonly_user or "").strip()
        password = self.db_readonly_password
        if not user:
            raise ValueError("在线查询必须设置 AGENTIC_BI_DB_READONLY_USER")
        if password is None or not password.get_secret_value():
            raise ValueError("在线查询必须设置 AGENTIC_BI_DB_READONLY_PASSWORD")
        return user, password
