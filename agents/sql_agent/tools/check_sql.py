"""
对 generate_sql_tool 输出的 JSON 做本地语法与安全校验（不访问数据库）。
支持 query_sqls 多条 SELECT，每条单独校验。
"""

from __future__ import annotations

import sys
from pathlib import Path

_sql_agent_dir = Path(__file__).resolve().parents[1]
if str(_sql_agent_dir) not in sys.path:
    sys.path.insert(0, str(_sql_agent_dir))

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from tools.generate_sql import GenerateSqlOutput
from tools.sql_format_rules import (
    normalize_sql,
    query_sql_format_ok,
    read_only_select_ok,
)


class CheckSqlOutput(BaseModel):
    syntax_ok: bool = Field(description="语法与本地安全规则是否通过")
    brief: str = Field(description="简要说明：通过时概括要点，失败时说明原因")


def check_generate_sql_model(payload: GenerateSqlOutput) -> CheckSqlOutput:
    """校验已解析的 GenerateSqlOutput。"""
    if not payload.query_sqls:
        return CheckSqlOutput(syntax_ok=False, brief="query_sqls 不能为空。")

    for i, sql_raw in enumerate(payload.query_sqls):
        sql_raw = str(sql_raw).strip()
        if not sql_raw:
            return CheckSqlOutput(
                syntax_ok=False, brief=f"query_sqls[{i}] 不能为空。"
            )
        if not query_sql_format_ok(sql_raw):
            return CheckSqlOutput(
                syntax_ok=False,
                brief=(
                    f"query_sqls[{i}] 格式不符：须以大写 SELECT 开头，"
                    "反引号内标识符全部小写，且单条内不得含分号。"
                ),
            )
        safe_ok, safe_reason = read_only_select_ok(sql_raw)
        if not safe_ok:
            return CheckSqlOutput(
                syntax_ok=False,
                brief=f"query_sqls[{i}] 安全校验未通过：{safe_reason}",
            )

    n = len(payload.query_sqls)
    return CheckSqlOutput(
        syntax_ok=True,
        brief=f"通过：JSON 字段完整，共 {n} 条只读 SELECT，格式与关键字安全校验均通过。",
    )


def check_generate_sql_payload(generate_sql_json: str) -> CheckSqlOutput:
    """从 JSON 字符串解析并校验。"""
    try:
        payload = GenerateSqlOutput.model_validate_json(generate_sql_json.strip())
    except Exception as e:
        return CheckSqlOutput(
            syntax_ok=False,
            brief=f"无法解析为 GenerateSqlOutput：{e}",
        )
    return check_generate_sql_model(payload)


class CheckSqlRunner:
    def invoke(self, generate_sql_json: str) -> str:
        out = check_generate_sql_payload(generate_sql_json)
        return out.model_dump_json(indent=2, ensure_ascii=False)


def build_check_sql_tool():
    runner = CheckSqlRunner()
    return StructuredTool.from_function(
        func=runner.invoke,
        name="check_sql_tool",
        description=(
            "检查 generate_sql_tool 输出的 JSON：本地校验字段完整性与 query_sqls 中"
            "每条 SELECT 的格式/只读安全。**不访问数据库**。"
        ),
    )


if __name__ == "__main__":
    demo = GenerateSqlOutput(
        analysis_grain="month",
        used_tables=["mv_monthly_sales"],
        query_sqls=["SELECT `year_month`, `total_gmv` FROM `mv_monthly_sales` LIMIT 5"],
        result_explanation="演示",
    ).model_dump_json(indent=2, ensure_ascii=False)
    print("===== 演示：check_sql_tool =====")
    print(CheckSqlRunner().invoke(demo))
