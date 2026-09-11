from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.common.llm import get_structured_llm, invoke_structured
from agents.common.paths import load_config_text
from agents.common.prompts import compose_system_prompt_parts
from agents.sql_agent.tools.rewrite_to_query import RewriteToQueryOutput


class GenerateSqlOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    analysis_grain: str = Field(
        default="",
        description="分析粒度（可选），如 year_month + customer_state；多 SQL 时可概括并列子问题",
    )
    used_tables: list[str] = Field(
        default_factory=list,
        description="所有 query_sqls 中实际使用的主要表或视图名（可选，去重）",
    )
    query_sqls: list[str] = Field(
        min_length=1,
        description=(
            "每条为完整可执行的 MySQL SELECT，一条内不得含分号；"
            "多子问题时优先与 sub_questions 一一对应，兼容参考 query_for_sql。"
        ),
    )
    result_explanation: str = Field(
        default="",
        description="说明口径、过滤条件、视图命中或回退原始表原因与业务含义；多 SQL 时按序号分述（可选）",
    )

    @model_validator(mode="before")
    @classmethod
    def _legacy_query_sql(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("query_sqls") is None:
            legacy = data.get("query_sql")
            if isinstance(legacy, str) and legacy.strip():
                data = {**data, "query_sqls": [legacy.strip()]}
        return data

    def normalized_sqls(self) -> list[str]:
        out: list[str] = []
        for q in self.query_sqls:
            s = q.strip()
            if s.endswith(";"):
                s = s[:-1].rstrip()
            out.append(s)
        return out


class GenerateSqlRunner:
    def __init__(self, model):
        self.model = model

    def invoke(self, rewrite_json: str, correction_context: str = "") -> str:
        """根据 rewrite_to_query 的结构化 JSON 生成 MySQL SQL。

        ``correction_context``：上游 check_sql / execute_sql 的失败说明，非空时会一并交给模型用于纠错。
        """
        payload = RewriteToQueryOutput.model_validate_json(rewrite_json.strip())

        system_prompt = compose_system_prompt_parts(
            "# Agent 背景规则\n\n"
            + load_config_text("sql_agent", "system_core.md"),
            "# 数据库表结构与视图字典\n\n"
            + load_config_text("sql_agent", "schema_dictionary.md"),
            "# SQL 生成工具规则\n\n"
            + load_config_text("sql_agent", "generate_sql_tool.md"),
        )

        human_content = (
            "以下为 rewrite_to_query_tool 的输出（JSON），请生成 SQL：\n\n"
            f"{payload.model_dump_json(indent=2, ensure_ascii=False)}"
            "\n\n请优先依据 sub_questions 生成 query_sqls，若无 sub_questions 再回退参考 query_for_sql。"
        )
        cc = (correction_context or "").strip()
        if cc:
            human_content += (
                "\n\n## 上一次校验或执行的纠错上下文（请据此修正 query_sqls 及说明字段）：\n\n"
                f"{cc}"
            )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_content),
        ]
        resp = invoke_structured(GenerateSqlOutput, messages, model=self.model)
        if not isinstance(resp, GenerateSqlOutput):
            resp = GenerateSqlOutput.model_validate(resp)
        return resp.model_dump_json(
            indent=2,
            ensure_ascii=False,
            exclude_none=True,
            exclude_defaults=True,
        )


def build_generate_sql_tool(model=None):
    if model is None:
        model = get_structured_llm()
    runner = GenerateSqlRunner(model=model)
    return StructuredTool.from_function(
        func=runner.invoke,
        name="generate_sql_tool",
        description=(
            "根据 rewrite_to_query_tool 输出的 JSON（优先字段：sub_questions；"
            "兼容字段：query_for_sql）生成 MySQL SELECT 列表（query_sqls）与分析说明。"
            "可选参数 correction_context：填入 check_sql / execute_sql 的错误说明以供纠错重试。"
        ),
    )


# 本地演示：命中单视图（可在 sql_agent 下 python -m tools.generate_sql，或在 tools 下 python generate_sql.py）
DEMO_REWRITE_JSON = RewriteToQueryOutput(
    query_for_sql="2017 年 GMV 是多少？按月和各州排名的趋势怎样？",
    hit_pre_agg_view=True,
    candidate_views=["mv_monthly_sales", "mv_state_sales"],
    confidence=0.95,
).model_dump_json(indent=2, ensure_ascii=False)


if __name__ == "__main__":
    print("===== 演示：generate_sql_tool =====")
    print("输入 rewrite_json:\n")
    print(DEMO_REWRITE_JSON)
    print()
    tool = build_generate_sql_tool(get_structured_llm())
    print(tool.invoke({"rewrite_json": DEMO_REWRITE_JSON}))
