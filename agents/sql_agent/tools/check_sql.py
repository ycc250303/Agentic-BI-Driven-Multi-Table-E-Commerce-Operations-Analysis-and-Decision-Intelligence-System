"""
对 generate_sql_tool 输出的 JSON 做本地语法与安全校验（不访问数据库）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_sql_agent_dir = Path(__file__).resolve().parents[1]
if str(_sql_agent_dir) not in sys.path:
    sys.path.insert(0, str(_sql_agent_dir))

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from tools.generate_sql import GenerateSqlOutput


class CheckSqlOutput(BaseModel):
    syntax_ok: bool = Field(description="语法与本地安全规则是否通过")
    brief: str = Field(description="简要说明：通过时概括要点，失败时说明原因")


def normalize_sql(sql: str) -> str:
    s = sql.strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s


def query_sql_format_ok(sql: str) -> bool:
    """与 generate_sql 一致：须以大写 SELECT 开头，反引号内标识符全部小写。"""
    s = sql.strip()
    if not s.startswith("SELECT"):
        return False
    for m in re.finditer(r"`([^`]*)`", s):
        inner = m.group(1)
        if inner and inner != inner.lower():
            return False
    return True


def read_only_sql_ok(sql: str) -> tuple[bool, str]:
    s = normalize_sql(sql)
    if ";" in s:
        return False, "不允许包含多条语句或语句内分号"
    if not s.upper().startswith("SELECT"):
        return False, "仅允许 SELECT 查询"
    no_str = re.sub(r"'(?:[^'\\]|\\.)*'", "''", s)
    no_id = re.sub(r"`[^`]*`", "`x`", no_str)
    banned = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|"
        r"GRANT|REVOKE|CALL|EXECUTE|INTO\s+OUTFILE|LOAD\s+DATA)\b",
        re.IGNORECASE,
    )
    if banned.search(no_id):
        return False, "检测到非只读或高风险 SQL 片段"
    return True, ""


def check_generate_sql_model(payload: GenerateSqlOutput) -> CheckSqlOutput:
    """校验已解析的 GenerateSqlOutput。"""
    if not payload.query_sql.strip():
        return CheckSqlOutput(syntax_ok=False, brief="query_sql 不能为空。")
    if not payload.used_tables:
        return CheckSqlOutput(syntax_ok=False, brief="used_tables 不能为空。")
    if not payload.analysis_grain.strip():
        return CheckSqlOutput(syntax_ok=False, brief="analysis_grain 不能为空。")
    if not payload.result_explanation.strip():
        return CheckSqlOutput(syntax_ok=False, brief="result_explanation 不能为空。")

    sql_raw = payload.query_sql.strip()
    if not query_sql_format_ok(sql_raw):
        return CheckSqlOutput(
            syntax_ok=False,
            brief="query_sql 格式不符：须以大写 SELECT 开头，且反引号内标识符全部小写。",
        )
    safe_ok, safe_reason = read_only_sql_ok(sql_raw)
    if not safe_ok:
        return CheckSqlOutput(syntax_ok=False, brief=safe_reason)

    return CheckSqlOutput(
        syntax_ok=True,
        brief="通过：JSON 字段完整，query_sql 为约定格式的只读 SELECT。",
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
            "检查 generate_sql_tool 输出的 JSON：本地校验字段完整性与 query_sql 格式/只读安全。"
            "返回仅含 syntax_ok 与 brief，不连接数据库。"
        ),
    )


if __name__ == "__main__":
    demo = GenerateSqlOutput(
        analysis_grain="month",
        used_tables=["mv_monthly_sales"],
        query_sql="SELECT `year_month`, `total_gmv` FROM `mv_monthly_sales` LIMIT 5",
        result_explanation="演示",
    ).model_dump_json(indent=2, ensure_ascii=False)
    print("===== 演示：check_sql_tool =====")
    print(CheckSqlRunner().invoke(demo))
