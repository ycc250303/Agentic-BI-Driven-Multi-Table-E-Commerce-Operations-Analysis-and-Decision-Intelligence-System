"""
对 generate_sql_tool 输出的 JSON 做本地格式与只读校验（不访问数据库）。
支持 query_sqls 多条 SELECT，每条单独校验。不是 MySQL 语法解析。
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agents.sql_agent.tools.generate_sql import GenerateSqlOutput
from agents.sql_agent.tools.sql_format_rules import (
    query_sql_format_ok,
    read_only_select_ok,
)


class CheckSqlOutput(BaseModel):
    syntax_ok: bool = Field(description="格式与本地只读规则是否通过（字段名保持兼容）")
    brief: str = Field(description="简要说明：通过时概括要点，失败时说明原因")


def check_generate_sql_model(payload: GenerateSqlOutput) -> CheckSqlOutput:
    """对已解析的 GenerateSqlOutput 逐条做格式 + 只读校验。

    入参：合法的 ``GenerateSqlOutput``。
    返回：``syntax_ok`` / ``brief``（字段名兼容旧契约，不是 MySQL 语法解析）。
    失败：任一条空 SQL、格式不符或含非只读片段即 ``syntax_ok=False``，不抛异常。
    """
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
    """解析 generate JSON 再交给 ``check_generate_sql_model``。

    失败：JSON / schema 非法时返回 ``syntax_ok=False``，不抛给调用方。
    """
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
        """流水线入口：返回 CheckSqlOutput JSON。不访问数据库。"""
        out = check_generate_sql_payload(generate_sql_json)
        return out.model_dump_json(indent=2, ensure_ascii=False)


def build_check_sql_tool():
    """装配 ``check_sql_tool``（无 LLM、无数据库）。"""
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
