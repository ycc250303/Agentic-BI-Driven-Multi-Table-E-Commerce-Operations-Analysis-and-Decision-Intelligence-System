import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_sql_agent_dir = Path(__file__).resolve().parents[1]
if str(_sql_agent_dir) not in sys.path:
    sys.path.insert(0, str(_sql_agent_dir))

from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from tools.rewrite_to_query import RewriteToQueryOutput

class GenerateSqlOutput(BaseModel):
    analysis_grain: str = Field(description="分析粒度，如 year_month + customer_state")
    used_tables: list[str] = Field(description="query_sql 中实际使用的主要表或视图名")
    query_sql: str = Field(
        description=(
            "完整可执行的 MySQL SELECT。"
            "表/视图/列/别名须为小写并用反引号包裹；SQL 关键字与 MySQL 内建函数名须大写。"
        )
    )
    result_explanation: str = Field(
        description="说明口径、过滤条件、视图命中或回退原始表原因与业务含义"
    )

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


def _query_sql_format_ok(sql: str) -> bool:
    """表/视图/列：小写+反引号；语句须以大写 SELECT 开头（见 generate_sql_tool.md）。"""
    s = sql.strip()
    if not s.startswith("SELECT"):
        return False
    for m in re.finditer(r"`([^`]*)`", s):
        inner = m.group(1)
        if inner and inner != inner.lower():
            return False
    return True


class GenerateSqlRunner:
    def __init__(self, model, max_retries: int = 3):
        self.structured_model = model.with_structured_output(GenerateSqlOutput)
        self.max_retries = max_retries

    def invoke(self, rewrite_json: str, correction_context: str = "") -> str:
        """根据 rewrite_to_query 的结构化 JSON 生成 MySQL SQL。

        ``correction_context``：上游 check_sql / execute_sql 的失败说明，非空时会一并交给模型用于纠错。
        """
        payload = RewriteToQueryOutput.model_validate_json(rewrite_json.strip())

        background_prompt = _load_prompt("system_core.md")
        schema_prompt = _load_prompt("schema_dictionary.md")
        sql_task_prompt = _load_prompt("generate_sql_tool.md")
        system_prompt = "\n\n".join(
            [
                "# Agent 背景规则",
                background_prompt,
                "# 数据库表结构与视图字典",
                schema_prompt,
                "# SQL 生成工具规则",
                sql_task_prompt,
            ]
        )

        human_content = (
            "以下为 rewrite_to_query_tool 的输出（JSON），请生成 SQL：\n\n"
            f"{payload.model_dump_json(indent=2, ensure_ascii=False)}"
        )
        cc = (correction_context or "").strip()
        if cc:
            human_content += (
                "\n\n## 上一次校验或执行的纠错上下文（请据此修正 query_sql 及说明字段）：\n\n"
                f"{cc}"
            )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_content),
        ]

        last_error: Exception | None = None
        resp: GenerateSqlOutput | None = None

        for _ in range(self.max_retries):
            try:
                candidate: Any = self.structured_model.invoke(messages)
                if isinstance(candidate, GenerateSqlOutput):
                    resp = candidate
                elif isinstance(candidate, dict):
                    resp = GenerateSqlOutput.model_validate(candidate)
                else:
                    resp = GenerateSqlOutput.model_validate(candidate)

                if not resp.query_sql.strip():
                    raise ValueError("query_sql 不能为空")
                if not resp.used_tables:
                    raise ValueError("used_tables 不能为空")
                if not resp.analysis_grain.strip():
                    raise ValueError("analysis_grain 不能为空")
                if not resp.result_explanation.strip():
                    raise ValueError("result_explanation 不能为空")
                if not _query_sql_format_ok(resp.query_sql):
                    raise ValueError(
                        "query_sql 格式不符：须以大写 SELECT 开头，且反引号内标识符全部小写"
                    )

                break
            except Exception as e:
                last_error = e

        if resp is None:
            raise RuntimeError(
                f"generate_sql_tool 在 {self.max_retries} 次尝试后仍未获得符合要求的输出: {last_error}"
            )

        return resp.model_dump_json(indent=2, ensure_ascii=False)

def build_generate_sql_tool(model):
    runner = GenerateSqlRunner(model=model, max_retries=3)
    return StructuredTool.from_function(
        func=runner.invoke,
        name="generate_sql_tool",
        description=(
            "根据 rewrite_to_query_tool 输出的 JSON（字段：query_for_sql、hit_pre_agg_view、"
            "candidate_views、confidence）生成 MySQL SELECT 与分析说明。"
            "可选参数 correction_context：填入 check_sql / execute_sql 的错误说明以供纠错重试。"
        ),
    )


# 本地演示：命中单视图（可在 sql_agent 下 python -m tools.generate_sql，或在 tools 下 python generate_sql.py）
DEMO_REWRITE_JSON = RewriteToQueryOutput(
    query_for_sql="2017 年 GMV 是多少？按月和各州排名的趋势怎样？",
    hit_pre_agg_view=True,
    candidate_views=["mv_monthly_sales","mv_state_sales"],
    confidence=0.95,
).model_dump_json(indent=2, ensure_ascii=False)


if __name__ == "__main__":
    from llm import get_llm

    print("===== 演示：generate_sql_tool =====")
    print("输入 rewrite_json:\n")
    print(DEMO_REWRITE_JSON)
    print()
    tool = build_generate_sql_tool(get_llm())
    print(tool.invoke({"rewrite_json": DEMO_REWRITE_JSON}))
