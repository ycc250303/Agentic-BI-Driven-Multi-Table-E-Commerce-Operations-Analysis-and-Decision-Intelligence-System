from pathlib import Path
from functools import lru_cache
from typing import Any

from langchain.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field


class RewriteToQueryOutput(BaseModel):
    query_for_sql: str = Field(description="专业的、用于 SQL 生成的自然语言查询指令")
    hit_pre_agg_view: bool = Field(description="是否命中预聚合视图")
    candidate_views: list[str] = Field(description="候选预聚合视图名称列表")
    confidence: float = Field(description="解析置信度，范围 0 到 1", ge=0, le=1)


def _project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config" / "data_analysis_agent").exists():
            return parent
    raise RuntimeError("未找到项目根目录下的 config/data_analysis_agent 目录。")


@lru_cache(maxsize=8)
def _load_prompt(name: str) -> str:
    prompt_path = _project_root() / "config" / "data_analysis_agent" / name
    return prompt_path.read_text(encoding="utf-8")


class RewriteToQueryRunner:
    def __init__(self, model, max_retries: int = 3):
        self.structured_model = model.with_structured_output(RewriteToQueryOutput)
        self.max_retries = max_retries

    def invoke(self, query: str) -> str:
        """将自然语言问题转换为查询工具输入。"""
        background_prompt = _load_prompt("system_core.md")
        schema_prompt = _load_prompt("schema_dictionary.md")
        rewrite_prompt = _load_prompt("rewrite_to_query_tool.md")
        system_prompt = "\n\n".join(
            [
                "# Agent 背景规则",
                background_prompt,
                "# 数据库表结构与视图字典",
                schema_prompt,
                "# 转写工具规则",
                rewrite_prompt,
            ]
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=query),
        ]
        last_error: Exception | None = None
        resp: RewriteToQueryOutput | None = None

        for _ in range(self.max_retries):
            try:
                candidate: Any = self.structured_model.invoke(messages)
                # 再次显式校验，确保最终输出严格符合 schema。
                if isinstance(candidate, RewriteToQueryOutput):
                    resp = candidate
                elif isinstance(candidate, dict):
                    resp = RewriteToQueryOutput.model_validate(candidate)
                else:
                    resp = RewriteToQueryOutput.model_validate(candidate)
                if (not resp.candidate_views and resp.hit_pre_agg_view) or (
                    resp.candidate_views and not resp.hit_pre_agg_view
                ):
                    raise ValueError(
                        "输出字段不一致：candidate_views 与 hit_pre_agg_view 必须一致"
                    )
                break
            except Exception as e:
                last_error = e

        if resp is None:
            raise RuntimeError(
                f"rewrite_to_query_tool 在 {self.max_retries} 次尝试后仍未获得符合 schema 的输出: {last_error}"
            )

        return resp.model_dump_json(indent=2, ensure_ascii=False)


def build_rewrite_to_query_tool(model):
    runner = RewriteToQueryRunner(model=model, max_retries=3)
    return StructuredTool.from_function(
        func=runner.invoke,
        name="rewrite_to_query_tool",
        description="将自然语言问题转换为查询工具的输入。",
    )


def build_tools(model):
    return [build_rewrite_to_query_tool(model)]