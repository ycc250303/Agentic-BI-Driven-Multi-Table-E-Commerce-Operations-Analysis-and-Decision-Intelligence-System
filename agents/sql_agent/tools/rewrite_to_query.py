from pathlib import Path
from functools import lru_cache
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, model_validator


class QueryScope(BaseModel):
    kind: Literal["platform", "inherit_previous", "explicit_filter"] = Field(
        default="platform",
        description=(
            "子问题作用域：platform=全局；inherit_previous=继承前序子问题筛选对象；"
            "explicit_filter=显式过滤条件。"
        ),
    )
    inherit_from: str | None = Field(
        default=None, description="当 kind=inherit_previous 时，引用的子问题 ID（如 q1）"
    )
    explicit_filter: str = Field(
        default="", description="当 kind=explicit_filter 时，可执行的自然语言过滤说明"
    )

    @model_validator(mode="after")
    def _scope_consistency(self) -> "QueryScope":
        if self.kind == "inherit_previous" and not (self.inherit_from or "").strip():
            raise ValueError("scope.kind=inherit_previous 时，inherit_from 不能为空")
        if self.kind != "inherit_previous":
            self.inherit_from = None
        if self.kind != "explicit_filter":
            self.explicit_filter = ""
        return self


class SubQuestion(BaseModel):
    id: str = Field(description="子问题 ID（如 q1、q2）")
    question_zh: str = Field(description="面向 SQL 的子问题中文描述")
    metric_key: str = Field(
        description=(
            "语义指标键（如 gmv_total、on_time_rate、payment_popularity、"
            "bad_review_count、bad_review_rate）"
        )
    )
    dimensions: list[str] = Field(
        default_factory=list,
        description="目标分析维度（如 year_month、customer_state、payment_type）",
    )
    time_range: str = Field(default="", description="时间范围说明（如 2017、最近12个月）")
    aggregation: str = Field(default="", description="聚合/排序目标（如 top1、top10、trend）")
    scope: QueryScope = Field(
        default_factory=QueryScope, description="子问题作用域配置"
    )


class RewriteToQueryOutput(BaseModel):
    query_for_sql: str = Field(
        default="",
        description="专业的、用于 SQL 生成的自然语言查询指令（兼容字段）",
    )
    sub_questions: list[SubQuestion] = Field(
        default_factory=list,
        description=(
            "结构化子问题列表（推荐主用）。当用户一次输入多个问题时，"
            "每个子意图应拆分为独立条目并保留作用域关系。"
        ),
    )
    hit_pre_agg_view: bool = Field(description="是否命中预聚合视图")
    candidate_views: list[str] = Field(description="候选预聚合视图名称列表")
    confidence: float = Field(description="解析置信度，范围 0 到 1", ge=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def _legacy_compat(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        query_for_sql = str(data.get("query_for_sql") or "").strip()
        sub_questions = data.get("sub_questions")
        if (not sub_questions) and query_for_sql:
            data = {
                **data,
                "sub_questions": [
                    {
                        "id": "q1",
                        "question_zh": query_for_sql,
                        "metric_key": "unspecified",
                        "dimensions": [],
                        "time_range": "",
                        "aggregation": "",
                        "scope": {"kind": "platform"},
                    }
                ],
            }
        return data

    @model_validator(mode="after")
    def _post_checks(self) -> "RewriteToQueryOutput":
        if (not self.candidate_views and self.hit_pre_agg_view) or (
            self.candidate_views and not self.hit_pre_agg_view
        ):
            raise ValueError("输出字段不一致：candidate_views 与 hit_pre_agg_view 必须一致")
        if not self.sub_questions:
            raise ValueError("sub_questions 不能为空")

        ids = [s.id for s in self.sub_questions if (s.id or "").strip()]
        if len(ids) != len(self.sub_questions):
            raise ValueError("sub_questions 中存在空 id")
        if len(set(ids)) != len(ids):
            raise ValueError("sub_questions.id 必须唯一")

        known = set(ids)
        for sq in self.sub_questions:
            if sq.scope.kind == "inherit_previous":
                ref = sq.scope.inherit_from or ""
                if ref not in known:
                    raise ValueError(
                        f"sub_questions[{sq.id}] 继承目标 {ref} 不存在于 sub_questions.id"
                    )

        if not self.query_for_sql.strip():
            self.query_for_sql = "；".join(sq.question_zh for sq in self.sub_questions)
        return self


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

    def invoke(self, query: str, correction_context: str = "") -> str:
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

        human_content = str(query)
        cc = (correction_context or "").strip()
        if cc:
            human_content += (
                "\n\n## 上一次结构化转写校验反馈（请据此修正 sub_questions 与作用域）：\n\n"
                f"{cc}"
            )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_content),
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
                break
            except Exception as e:
                last_error = e

        if resp is None:
            raise RuntimeError(
                f"rewrite_to_query_tool 在 {self.max_retries} 次尝试后仍未获得符合 schema 的输出: {last_error}"
            )

        return resp.model_dump_json(
            indent=2,
            ensure_ascii=False,
            exclude_none=True,
            exclude_defaults=True,
        )


def build_rewrite_to_query_tool(model, max_retries: int = 3):
    runner = RewriteToQueryRunner(model=model, max_retries=max_retries)
    return StructuredTool.from_function(
        func=runner.invoke,
        name="rewrite_to_query_tool",
        description=(
            "将自然语言问题转换为查询工具输入，输出结构化 sub_questions（含作用域）；"
            "可选参数 correction_context：填入结构化校验反馈以供重写。"
        ),
    )


# 本地演示用示例问题（运行：在 agents/sql_agent 目录下 python -m tools.rewrite_to_query）
DEMO_QUESTION = "最近12个月的月度GMV趋势如何？"


if __name__ == "__main__":
    import sys

    SQL_AGENT_DIR = Path(__file__).resolve().parents[1]
    if str(SQL_AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(SQL_AGENT_DIR))

    from llm import get_llm

    print("===== 演示：rewrite_to_query_tool =====")
    print(f"输入: {DEMO_QUESTION}\n")
    tool = build_rewrite_to_query_tool(get_llm())
    print(tool.invoke({"query": DEMO_QUESTION}))