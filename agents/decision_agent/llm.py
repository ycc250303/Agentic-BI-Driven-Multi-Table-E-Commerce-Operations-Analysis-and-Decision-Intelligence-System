from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek


@lru_cache(maxsize=1)
def get_llm() -> ChatDeepSeek:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "缺少环境变量 DEEPSEEK_API_KEY。请在 .env 或系统环境变量中配置后再运行。"
        )
    return ChatDeepSeek(
        model="deepseek-v4-flash",
        extra_body={"thinking": {"type": "disabled"}},
    )
