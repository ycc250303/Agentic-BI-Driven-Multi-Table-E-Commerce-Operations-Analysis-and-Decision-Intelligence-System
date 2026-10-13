"""DeepSeek 与通义千问的唯一模型入口。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from agentic_bi.core.settings import ModelProvider, Settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)
StructuredMethod = Literal["function_calling", "json_mode", "json_schema"]


class ModelGateway:
    """缓存模型客户端并统一普通调用和结构化调用。

    这里只处理客户端级超时与瞬时重试。SQL/schema 修复由 LangGraph 的有界循环负责。
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._models: dict[tuple[ModelProvider, float, bool], BaseChatModel] = {}

    def get_model(
        self,
        *,
        provider: ModelProvider | None = None,
        temperature: float = 0,
        structured: bool = False,
    ) -> BaseChatModel:
        """按提供商、温度和是否结构化调用，取缓存的聊天模型。

        输入：
        - ``provider``：为空时用 ``Settings.llm_provider``
        - ``temperature``：默认 0
        - ``structured``：为真时供结构化输出使用，并关闭 DeepSeek 思考模式

        输出：
        - ``BaseChatModel``：相同三元组复用同一客户端
        """
        selected = provider or self._settings.llm_provider
        cache_key = (selected, temperature, structured)
        if cache_key not in self._models:
            self._models[cache_key] = self._build_model(
                provider=selected,
                temperature=temperature,
                structured=structured,
            )
        return self._models[cache_key]

    def invoke(
        self,
        messages: Sequence[BaseMessage],
        *,
        provider: ModelProvider | None = None,
        temperature: float = 0,
        config: RunnableConfig | None = None,
    ) -> BaseMessage:
        """发送一轮自由文本对话。

        输入：
        - ``messages``：LangChain 消息序列
        - ``provider``：含义同 ``get_model``
        - ``temperature``：含义同 ``get_model``
        - ``config``：可选 ``RunnableConfig``
        - ``config.run_name``：本次运行名
        - ``config.tags``：检索标签
        - ``config.metadata``：上下文字典
        - ``config.recursion_limit``：图递归上限

        输出：
        - ``BaseMessage``：不解析业务 JSON，也不重试 schema 错误
        """
        model = self.get_model(provider=provider, temperature=temperature)
        return model.invoke(list(messages), config=config)

    def invoke_structured(
        self,
        schema: type[SchemaT],
        messages: Sequence[BaseMessage],
        *,
        provider: ModelProvider | None = None,
        method: StructuredMethod | None = None,
        config: RunnableConfig | None = None,
    ) -> SchemaT:
        """调用模型并校验为指定 Pydantic 模型。

        输入：
        - ``schema``：期望的 Pydantic 类型
        - ``messages``：提示消息
        - ``provider``：为空时用 ``Settings.llm_provider``
        - ``method``：为空时由 ``_structured_method`` 决定
        - ``config``：同 ``invoke``

        本方法固定走 ``structured=True`` 的客户端。

        输出：
        - ``schema`` 的实例：返回值类型不符时抛 ``TypeError``
        """
        selected = provider or self._settings.llm_provider
        selected_method = method or self._structured_method(selected)
        model = self.get_model(provider=selected, structured=True)
        runnable = model.with_structured_output(schema, method=selected_method)
        result = runnable.invoke(list(messages), config=config)
        if not isinstance(result, schema):
            raise TypeError(f"结构化模型返回值不是 {schema.__name__}")
        return result

    def _build_model(
        self,
        *,
        provider: ModelProvider,
        temperature: float,
        structured: bool,
    ) -> BaseChatModel:
        """按提供商构造一个聊天模型客户端。

        输入：
        - ``provider``：模型提供商
        - ``temperature``：采样温度
        - ``structured``：为真时不打开 DeepSeek 思考模式

        模型名、API Key、超时和客户端重试次数来自 ``Settings``。

        输出：
        - DeepSeek：``ChatDeepSeek``
        - 通义千问：指向百炼 compatible-mode 的 ``ChatOpenAI``
        """
        common = {
            "model": self._settings.model_for(provider),
            "api_key": self._settings.api_key_for(provider),
            "temperature": temperature,
            "timeout": self._settings.llm_timeout_seconds,
            "max_retries": self._settings.llm_max_retries,
        }

        if provider == ModelProvider.DEEPSEEK:
            extra_body = None
            if self._settings.llm_thinking_enabled and not structured:
                extra_body = {"thinking": {"type": "enabled"}}
            return ChatDeepSeek(**common, extra_body=extra_body)

        return ChatOpenAI(
            **common,
            base_url=str(self._settings.dashscope_base_url),
        )

    @staticmethod
    def _structured_method(provider: ModelProvider) -> StructuredMethod:
        """选择该提供商可用的结构化输出方法。

        输入：
        - ``provider``：``ModelProvider``

        输出：
        - DeepSeek：``function_calling``
        - 通义千问：``json_schema``
        """
        if provider == ModelProvider.DEEPSEEK:
            return "function_calling"
        return "json_schema"
