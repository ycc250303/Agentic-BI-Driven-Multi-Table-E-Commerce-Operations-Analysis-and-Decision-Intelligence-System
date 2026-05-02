"""
连接 MySQL 执行 generate_sql_tool 输出的 JSON 中的 query_sql，返回结构化结果摘要。

编排上应在链中先跑 check_sql_tool；本工具不重复其语法/只读校验（仅做空 query 防护）。
单独调用本工具时请自行保证输入已通过 check_sql_tool。
"""

from __future__ import annotations

import csv
import os
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

_sql_agent_dir = Path(__file__).resolve().parents[1]
if str(_sql_agent_dir) not in sys.path:
    sys.path.insert(0, str(_sql_agent_dir))

import pymysql
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from pymysql.cursors import DictCursor

from tools.check_sql import normalize_sql
from tools.generate_sql import GenerateSqlOutput


def _db_config_from_env() -> dict[str, Any]:
    """仅从环境变量读取连接参数，不设代码内默认值。"""
    keys = [
        "AGENTIC_BI_DB_HOST",
        "AGENTIC_BI_DB_PORT",
        "AGENTIC_BI_DB_USER",
        "AGENTIC_BI_DB_PASSWORD",
        "AGENTIC_BI_DB_NAME",
    ]
    missing = [k for k in keys if os.environ.get(k) in (None, "")]
    if missing:
        raise ValueError("缺少或未设置数据库环境变量：" + ", ".join(missing))
    try:
        port = int(os.environ["AGENTIC_BI_DB_PORT"])
    except ValueError as e:
        raise ValueError("AGENTIC_BI_DB_PORT 须为整数") from e
    return {
        "host": os.environ["AGENTIC_BI_DB_HOST"],
        "port": port,
        "user": os.environ["AGENTIC_BI_DB_USER"],
        "password": os.environ["AGENTIC_BI_DB_PASSWORD"],
        "database": os.environ["AGENTIC_BI_DB_NAME"],
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
    }


DEFAULT_MAX_ROWS = int(os.environ.get("AGENTIC_BI_SQL_MAX_ROWS", "5000"))


def _query_result_csv_dir() -> Path:
    raw = os.environ.get("AGENTIC_BI_SQL_CSV_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (_sql_agent_dir / "query_results").resolve()


def _write_query_result_csv(
    columns: list[str], rows: list[dict[str, Any]]
) -> Path:
    """结果写入 CSV，文件名为可读时间戳（精确到秒）。冲突时追加 _1、_2…"""
    dest_dir = _query_result_csv_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    # 例：2026-05-02 20-47-29（年月日、时分秒各段内用“-”，日与时刻之间空格）
    ts = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    path = dest_dir / f"{ts}.csv"
    n = 1
    while path.exists():
        path = dest_dir / f"{ts}_{n}.csv"
        n += 1
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c) if r.get(c) is not None else "" for c in columns})
    return path.resolve()


def _json_safe_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return v


def _infer_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int) and not isinstance(v, bool):
        return "integer"
    if isinstance(v, float):
        return "float"
    if isinstance(v, Decimal):
        return "decimal"
    if isinstance(v, (datetime, date)):
        return "datetime"
    return "string"


class ColumnProfile(BaseModel):
    name: str = Field(description="列名")
    inferred_type: str = Field(description="根据样本推断的类型标签")
    non_null_count: int = Field(description="非空行数（在返回样本内）")
    null_count: int = Field(description="空值行数")
    sample_values: list[Any] = Field(
        default_factory=list, description="最多 3 个示例值，便于下游理解语义"
    )


class ExecuteSqlOutput(BaseModel):
    ok: bool = Field(description="整体是否成功拿到结果集")
    sql_syntax_ok: bool = Field(
        description="输入侧：JSON 可解析且 query_sql 非空。SQL 规则校验由链路上的 check_sql_tool 完成，本工具不重复"
    )
    executed: bool = Field(description="是否已在数据库上执行")
    error_stage: str | None = Field(
        default=None,
        description="失败阶段：parse_input | sql_local | env_config | db_connect | db_execute | csv_write",
    )
    error_message: str | None = Field(default=None, description="错误信息（中文简述）")

    result_explanation: str = Field(default="", description="来自输入的业务口径说明")
    query_sql: str = Field(default="", description="实际执行的 SQL（规范化后）")

    row_count_returned: int = Field(default=0, description="本次返回的行数")
    truncated: bool = Field(default=False, description="是否因行数上限截断")

    columns: list[str] = Field(default_factory=list, description="结果列顺序")
    column_profiles: list[ColumnProfile] = Field(
        default_factory=list, description="列级摘要，便于可视化映射字段类型"
    )
    result_csv_filename: str = Field(
        default="",
        description="查询结果 CSV 文件名（如 2026-05-02 20-47-29.csv）；无文件时为空",
    )
    result_csv_path: str = Field(
        default="",
        description="查询结果 CSV 绝对路径；未写入时为空",
    )

    data_summary_zh: str = Field(
        default="",
        description="面向人与下游 LLM 的简短中文数据摘要",
    )
    execution_time_ms: float = Field(default=0.0, description="数据库执行耗时（毫秒）")


def _profile_columns(
    rows: list[dict[str, Any]], columns: list[str]
) -> list[ColumnProfile]:
    if not rows or not columns:
        return []
    n = len(rows)
    profiles: list[ColumnProfile] = []
    for col in columns:
        vals = [r.get(col) for r in rows]
        non_null = [v for v in vals if v is not None]
        null_count = n - len(non_null)
        inferred = "unknown"
        if non_null:
            inferred = _infer_type(non_null[0])
            for v in non_null[1:20]:
                t = _infer_type(v)
                if t != inferred:
                    inferred = "mixed"
                    break
        sample_raw = non_null[:3]
        sample = [_json_safe_value(x) for x in sample_raw]
        profiles.append(
            ColumnProfile(
                name=col,
                inferred_type=inferred,
                non_null_count=len(non_null),
                null_count=null_count,
                sample_values=sample,
            )
        )
    return profiles


def _build_summary_zh(
    row_count: int,
    truncated: bool,
    columns: list[str],
    profiles: list[ColumnProfile],
    execution_ms: float,
) -> str:
    parts = [
        f"查询返回 {row_count} 行",
        "（已截断）" if truncated else "",
        f"，耗时约 {execution_ms:.1f} ms。",
        f"共 {len(columns)} 列：{', '.join(columns[:12])}",
        " …" if len(columns) > 12 else "",
        "。",
    ]
    detail_lines: list[str] = []
    for p in profiles[:8]:
        if p.sample_values:
            detail_lines.append(
                f"{p.name}（{p.inferred_type}）非空 {p.non_null_count}，示例 {p.sample_values}。"
            )
    if detail_lines:
        parts.append("列摘要：" + " ".join(detail_lines))
    return "".join(parts)


class ExecuteSqlRunner:
    def __init__(
        self,
        db_config: dict[str, Any] | None = None,
        max_rows: int | None = None,
    ):
        self._db_config_override = db_config
        self.max_rows = max_rows if max_rows is not None else DEFAULT_MAX_ROWS

    def _resolve_db_config(self) -> dict[str, Any]:
        if self._db_config_override is not None:
            cfg = dict(self._db_config_override)
            cfg.setdefault("cursorclass", DictCursor)
            return cfg
        return _db_config_from_env()

    def invoke(self, generate_sql_json: str) -> str:
        """输入为 GenerateSqlOutput 的 JSON 字符串；输出为 ExecuteSqlOutput 的 JSON。"""
        payload: GenerateSqlOutput | None = None
        try:
            payload = GenerateSqlOutput.model_validate_json(generate_sql_json.strip())
        except Exception as e:
            out = ExecuteSqlOutput(
                ok=False,
                sql_syntax_ok=False,
                executed=False,
                error_stage="parse_input",
                error_message=f"无法解析为 GenerateSqlOutput：{e}",
                query_sql="",
            )
            return out.model_dump_json(indent=2, ensure_ascii=False)

        sql_raw = payload.query_sql.strip()
        sql = normalize_sql(sql_raw)
        if not sql_raw:
            out = ExecuteSqlOutput(
                ok=False,
                sql_syntax_ok=False,
                executed=False,
                error_stage="sql_local",
                error_message="query_sql 为空，请确保链路中已运行 check_sql_tool 且 generate_sql 输出有效",
                result_explanation=payload.result_explanation,
                query_sql="",
            )
            return out.model_dump_json(indent=2, ensure_ascii=False)

        try:
            db_cfg = self._resolve_db_config()
        except ValueError as e:
            out = ExecuteSqlOutput(
                ok=False,
                sql_syntax_ok=True,
                executed=False,
                error_stage="env_config",
                error_message=str(e),
                result_explanation=payload.result_explanation,
                query_sql=sql,
            )
            return out.model_dump_json(indent=2, ensure_ascii=False)

        conn = None
        t0 = time.perf_counter()
        rows_out: list[dict[str, Any]] = []
        truncated = False
        columns: list[str] = []

        try:
            conn = pymysql.connect(**db_cfg)
            with conn.cursor() as cursor:
                cursor.execute(sql)
                columns = [d[0] for d in (cursor.description or ())]
                batch = cursor.fetchmany(self.max_rows + 1)
                if len(batch) > self.max_rows:
                    truncated = True
                    batch = batch[: self.max_rows]
                for raw in batch:
                    row = {k: _json_safe_value(raw[k]) for k in raw}
                    rows_out.append(row)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            err_stage = "db_connect" if conn is None else "db_execute"
            err_msg = (
                f"数据库连接失败：{e}"
                if conn is None
                else f"执行失败（可能含语法或权限错误）：{e}"
            )
            executed = conn is not None
            out = ExecuteSqlOutput(
                ok=False,
                sql_syntax_ok=True,
                executed=executed,
                error_stage=err_stage,
                error_message=err_msg,
                result_explanation=payload.result_explanation,
                query_sql=sql,
                execution_time_ms=elapsed,
            )
            return out.model_dump_json(indent=2, ensure_ascii=False)
        finally:
            if conn is not None:
                conn.close()

        elapsed = (time.perf_counter() - t0) * 1000
        profiles = _profile_columns(rows_out, columns)
        summary = _build_summary_zh(
            len(rows_out), truncated, columns, profiles, elapsed
        )

        try:
            csv_path = _write_query_result_csv(columns, rows_out)
        except OSError as e:
            out = ExecuteSqlOutput(
                ok=False,
                sql_syntax_ok=True,
                executed=True,
                error_stage="csv_write",
                error_message=f"结果写入 CSV 失败：{e}",
                result_explanation=payload.result_explanation,
                query_sql=sql,
                row_count_returned=len(rows_out),
                truncated=truncated,
                columns=columns,
                column_profiles=profiles,
                data_summary_zh=summary,
                execution_time_ms=elapsed,
            )
            return out.model_dump_json(indent=2, ensure_ascii=False)

        out = ExecuteSqlOutput(
            ok=True,
            sql_syntax_ok=True,
            executed=True,
            error_stage=None,
            error_message=None,
            result_explanation=payload.result_explanation,
            query_sql=sql,
            row_count_returned=len(rows_out),
            truncated=truncated,
            columns=columns,
            column_profiles=profiles,
            result_csv_filename=csv_path.name,
            result_csv_path=str(csv_path),
            data_summary_zh=summary + f" 明细已写入 CSV：{csv_path.name}。",
            execution_time_ms=elapsed,
        )
        return out.model_dump_json(indent=2, ensure_ascii=False)


def build_execute_sql_tool():
    runner = ExecuteSqlRunner()
    return StructuredTool.from_function(
        func=runner.invoke,
        name="execute_sql_tool",
        description=(
            "在配置好环境变量后连接 MySQL，执行 generate_sql JSON 中的 query_sql。"
            "查询明细写入 CSV（文件名：YYYY-MM-DD HH-MM-SS.csv，日与时刻之间空格），工具返回路径与摘要而非原始行。"
            "可选环境变量 AGENTIC_BI_SQL_CSV_DIR 指定输出目录。"
            "链式编排下须先调用 check_sql_tool；本工具不重复 SQL 规则校验。"
        ),
    )


if __name__ == "__main__":
    for key in (
        "AGENTIC_BI_DB_HOST",
        "AGENTIC_BI_DB_PORT",
        "AGENTIC_BI_DB_USER",
        "AGENTIC_BI_DB_PASSWORD",
        "AGENTIC_BI_DB_NAME",
    ):
        if key not in os.environ:
            print(f"请设置环境变量 {key} 后再运行演示。", file=sys.stderr)
            sys.exit(1)

    demo = GenerateSqlOutput(
        analysis_grain="month",
        used_tables=["mv_monthly_sales"],
        query_sql="SELECT `year_month`, `total_gmv` FROM `mv_monthly_sales`",
        result_explanation="演示：取月度 GMV 前 5 行",
    ).model_dump_json(indent=2, ensure_ascii=False)
    print("===== 演示：execute_sql_tool =====")
    print(ExecuteSqlRunner().invoke(demo))
