from __future__ import annotations

from agents.sql_agent.tools.check_sql import (
    check_generate_sql_model,
    check_generate_sql_payload,
)
from agents.sql_agent.tools.generate_sql import GenerateSqlOutput


def _ok_sql() -> str:
    return "SELECT `year_month`, `total_gmv` FROM `mv_monthly_sales` LIMIT 5"


def test_check_accepts_readonly_select():
    payload = GenerateSqlOutput(
        analysis_grain="month",
        used_tables=["mv_monthly_sales"],
        query_sqls=[_ok_sql()],
        result_explanation="demo",
    )
    out = check_generate_sql_model(payload)
    assert out.syntax_ok is True
    assert "只读" in out.brief


def test_check_rejects_empty_query_sqls():
    payload = GenerateSqlOutput.model_construct(query_sqls=[])
    out = check_generate_sql_model(payload)
    assert out.syntax_ok is False
    assert "不能为空" in out.brief


def test_check_rejects_blank_sql():
    payload = GenerateSqlOutput(query_sqls=["   "], result_explanation="x")
    out = check_generate_sql_model(payload)
    assert out.syntax_ok is False
    assert "query_sqls[0]" in out.brief


def test_check_rejects_non_readonly_fragment():
    payload = GenerateSqlOutput(
        query_sqls=["SELECT * FROM t DROP TABLE x"],
        result_explanation="x",
    )
    out = check_generate_sql_model(payload)
    assert out.syntax_ok is False
    assert "安全校验" in out.brief


def test_check_payload_rejects_invalid_json():
    out = check_generate_sql_payload("not-json")
    assert out.syntax_ok is False
    assert "无法解析" in out.brief
