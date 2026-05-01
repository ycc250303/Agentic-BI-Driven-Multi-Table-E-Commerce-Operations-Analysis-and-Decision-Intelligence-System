import os
from functools import lru_cache

from langchain.agents import create_agent
from langchain_deepseek import ChatDeepSeek
from dotenv import load_dotenv


@lru_cache(maxsize=1)
def get_llm() -> ChatDeepSeek:
    load_dotenv()
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise RuntimeError(
            "缺少环境变量 DEEPSEEK_API_KEY。请先设置后再运行，例如："
            "export DEEPSEEK_API_KEY='your_api_key'"
        )
    return ChatDeepSeek(
        model="deepseek-v4-flash",
        extra_body={"thinking": {"type": "disabled"}},
    )


def build_agent(*, tools, middleware=None, system_prompt: str | None = None):
    model = get_llm()
    kwargs = {
        "model": model,
        "tools": tools,
    }
    if middleware is not None:
        kwargs["middleware"] = middleware
    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    return create_agent(**kwargs)
