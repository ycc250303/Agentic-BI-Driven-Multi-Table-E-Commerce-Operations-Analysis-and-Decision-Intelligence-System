"""
连接 MySQL 执行 generate_sql_tool 输出的 JSON 中的 query_sqls（可多条 SELECT），返回结构化结果摘要。

编排上应在链中先跑 check_sql_tool 做格式/只读预检。本工具在执行前再次做只读校验，
未通过的条目不发送到数据库（error_stage=sql_local）。
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

import pymysql
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from pymysql.cursors import DictCursor

from db_env import json_safe_value, pymysql_config
from agents.sql_agent.tools.generate_sql import GenerateSqlOutput
from agents.sql_agent.tools.sql_format_rules import normalize_sql, read_only_select_ok

_sql_agent_dir = Path(__file__).resolve().parents[1]


def _db_config_from_env() -> dict[str, Any]:
    """仅从环境变量读取连接参数，不设代码内默认值。"""
    cfg = pymysql_config(autocommit=False)
    cfg["cursorclass"] = DictCursor
    return cfg


DEFAULT_MAX_ROWS = int(os.environ.get("AGENTIC_BI_SQL_MAX_ROWS", "5000"))


def _query_result_csv_dir() -> Path:
    raw = os.environ.get("AGENTIC_BI_SQL_CSV_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (_sql_agent_dir / "query_results").resolve()


def _unique_csv_path(dest_dir: Path, stem: str) -> Path:
    """stem 不含 .csv；冲突时追加 _1、_2…"""
    path = dest_dir / f"{stem}.csv"
    n = 1
    while path.exists():
        path = dest_dir / f"{stem}_{n}.csv"
        n += 1
    return path


def _csv_stem(batch_ts: str, idx: int, n_sql: int) -> str:
    """多 SQL 用 时间戳_sqlN；单条仍只用时间戳，与历史文件名兼容。"""
    return f"{batch_ts}_sql{idx + 1}" if n_sql > 1 else batch_ts


def _reshape_single_column_ltr(
    columns: list[str], rows: list[dict[str, Any]]
) -> tuple[list[str], list[dict[str, Any]]]:
    """单列结果改成 metric,value，同一行从左往右写，避免表头在 A1、值在 A2。"""
    if len(columns) != 1:
        return columns, rows
    col = columns[0]
    wide = [
        {
            "metric": col,
            "value": r.get(col) if r.get(col) is not None else "",
        }
        for r in rows
    ]
    return ["metric", "value"], wide


def _write_query_result_csv(
    columns: list[str], rows: list[dict[str, Any]], *, file_stem: str
) -> Path:
    dest_dir = _query_result_csv_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = _unique_csv_path(dest_dir, file_stem)
    write_cols, write_rows = _reshape_single_column_ltr(columns, rows)
    # utf-8 无 BOM + LF：避免 Excel/编辑器把 BOM 当成空的第一列
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=write_cols,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for r in write_rows:
            writer.writerow(
                {c: r.get(c) if r.get(c) is not None else "" for c in write_cols}
            )
    return path.resolve()


def _try_write_error_csv(stem: str, stage: str, message: str) -> str:
    """失败条目也占 sqlN 文件位，避免出现 sql2/sql4 却缺 sql3。"""
    try:
        path = _write_query_result_csv(
            ["error_stage", "error_message"],
            [{"error_stage": stage, "error_message": message}],
            file_stem=stem,
        )
        return str(path)
    except OSError:
        return ""


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


class ExecuteSqlResultItem(BaseModel):
    """单条 SELECT 的执行结果与对应 CSV。"""

    index: int = Field(description="从 0 起的 SQL 序号")
    ok: bool = Field(description="本条是否成功返回并写出 CSV")
    row_count_returned: int = Field(default=0, description="本条返回行数")
    truncated: bool = Field(default=False, description="是否因行数上限截断")
    result_csv_path: str = Field(default="", description="本条结果 CSV 绝对路径")
    data_summary_zh: str = Field(default="", description="本条中文摘要")
    execution_time_ms: float = Field(default=0.0, description="本条数据库执行耗时（毫秒）")
    error_stage: str | None = Field(
        default=None,
        description="失败阶段：sql_local | db_execute | csv_write",
    )
    error_message: str | None = Field(default=None, description="本条错误简述")


class ExecuteSqlOutput(BaseModel):
    ok: bool = Field(description="全部 SQL 是否均成功")
    executed: bool = Field(description="是否至少有一次已在数据库上执行")
    error_stage: str | None = Field(
        default=None,
        description="整体失败阶段：parse_input | sql_local | env_config | db_connect",
    )
    error_message: str | None = Field(
        default=None, description="整体或聚合错误信息（任一条失败时会汇总）"
    )

    results: list[ExecuteSqlResultItem] = Field(
        default_factory=list, description="与 query_sqls 顺序一一对应"
    )

    row_count_returned: int = Field(
        default=0, description="各条返回行数之和；仅一条时即该行数"
    )
    truncated: bool = Field(default=False, description="任一条发生截断则为 true")

    data_summary_zh: str = Field(
        default="",
        description="各条摘要合并后的中文概述",
    )
    execution_time_ms: float = Field(
        default=0.0, description="各条 execution_time_ms 之和"
    )


def _profile_columns(
    rows: list[dict[str, Any]], columns: list[str]
) -> list[ColumnProfile]:
    """根据返回样本推断列类型、空值与示例，供中文摘要使用。"""
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
        sample = [json_safe_value(x) for x in sample_raw]
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
    """拼单条 SELECT 的中文结果摘要（行数、截断、耗时、列示例）。"""
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
        """解析 generate JSON，逐条只读校验后执行 SELECT，写出 CSV。

        入参：GenerateSqlOutput 的 JSON 字符串。
        返回：ExecuteSqlOutput JSON（``results`` 按条、以及聚合摘要）。
        失败：解析失败 ``parse_input``；缺连接配置 ``env_config``；单条只读未过
        ``sql_local`` 且该条不发往数据库；连库/执行/写 CSV 分别记对应 ``error_stage``。
        不向调用方抛业务异常。
        """
        payload: GenerateSqlOutput | None = None
        try:
            payload = GenerateSqlOutput.model_validate_json(generate_sql_json.strip())
        except Exception as e:
            out = ExecuteSqlOutput(
                ok=False,
                executed=False,
                error_stage="parse_input",
                error_message=f"无法解析为 GenerateSqlOutput：{e}",
            )
            return out.model_dump_json(
                indent=2, ensure_ascii=False, exclude_none=True, exclude_defaults=True
            )

        sql_list = payload.normalized_sqls()
        if not sql_list or any(not s for s in sql_list):
            out = ExecuteSqlOutput(
                ok=False,
                executed=False,
                error_stage="sql_local",
                error_message="query_sqls 为空或含空字符串，请确保链路中已运行 check_sql_tool 且 generate_sql 输出有效",
            )
            return out.model_dump_json(
                indent=2, ensure_ascii=False, exclude_none=True, exclude_defaults=True
            )

        try:
            db_cfg = self._resolve_db_config()
        except ValueError as e:
            out = ExecuteSqlOutput(
                ok=False,
                executed=False,
                error_stage="env_config",
                error_message=str(e),
            )
            return out.model_dump_json(
                indent=2, ensure_ascii=False, exclude_none=True, exclude_defaults=True
            )

        batch_ts = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        n_sql = len(sql_list)
        results: list[ExecuteSqlResultItem] = []
        conn = None
        any_executed = False

        try:
            conn = pymysql.connect(**db_cfg)
            any_executed = True
            with conn.cursor() as cursor:
                for idx, sql_raw in enumerate(sql_list):
                    sql = normalize_sql(sql_raw)
                    stem = _csv_stem(batch_ts, idx, n_sql)
                    # 第二道只读闸门：未通过的条目不发送到数据库
                    safe_ok, safe_reason = read_only_select_ok(sql)
                    if not safe_ok:
                        err_msg = f"只读校验未通过：{safe_reason}"
                        results.append(
                            ExecuteSqlResultItem(
                                index=idx,
                                ok=False,
                                result_csv_path=_try_write_error_csv(
                                    stem, "sql_local", err_msg
                                ),
                                error_stage="sql_local",
                                error_message=err_msg,
                            )
                        )
                        continue

                    t0 = time.perf_counter()
                    rows_out: list[dict[str, Any]] = []
                    truncated = False
                    columns: list[str] = []

                    try:
                        cursor.execute(sql)
                        columns = [d[0] for d in (cursor.description or ())]
                        batch = cursor.fetchmany(self.max_rows + 1)
                        if len(batch) > self.max_rows:
                            truncated = True
                            batch = batch[: self.max_rows]
                        for raw in batch:
                            row = {k: json_safe_value(raw[k]) for k in raw}
                            rows_out.append(row)
                    except Exception as e:
                        elapsed = (time.perf_counter() - t0) * 1000
                        err_msg = f"执行失败：{e}"
                        results.append(
                            ExecuteSqlResultItem(
                                index=idx,
                                ok=False,
                                result_csv_path=_try_write_error_csv(
                                    stem, "db_execute", err_msg
                                ),
                                execution_time_ms=elapsed,
                                error_stage="db_execute",
                                error_message=err_msg,
                            )
                        )
                        continue

                    elapsed = (time.perf_counter() - t0) * 1000
                    profiles = _profile_columns(rows_out, columns)
                    summary = _build_summary_zh(
                        len(rows_out), truncated, columns, profiles, elapsed
                    )
                    try:
                        csv_path = _write_query_result_csv(
                            columns, rows_out, file_stem=stem
                        )
                    except OSError as e:
                        results.append(
                            ExecuteSqlResultItem(
                                index=idx,
                                ok=False,
                                row_count_returned=len(rows_out),
                                truncated=truncated,
                                data_summary_zh=summary,
                                execution_time_ms=elapsed,
                                error_stage="csv_write",
                                error_message=f"结果写入 CSV 失败：{e}",
                            )
                        )
                        continue

                    results.append(
                        ExecuteSqlResultItem(
                            index=idx,
                            ok=True,
                            row_count_returned=len(rows_out),
                            truncated=truncated,
                            result_csv_path=str(csv_path),
                            data_summary_zh=summary
                            + f" 明细已写入 CSV：{csv_path.name}。",
                            execution_time_ms=elapsed,
                        )
                    )
        except Exception as e:
            out = ExecuteSqlOutput(
                ok=False,
                executed=any_executed,
                error_stage="db_connect" if conn is None else "db_execute",
                error_message=(
                    f"数据库连接失败：{e}"
                    if conn is None
                    else f"执行过程异常：{e}"
                ),
                results=results,
            )
            return out.model_dump_json(
                indent=2, ensure_ascii=False, exclude_none=True, exclude_defaults=True
            )
        finally:
            if conn is not None:
                conn.close()

        all_ok = bool(results) and all(r.ok for r in results)
        err_msgs = [
            f"[SQL#{r.index + 1}] {r.error_message}"
            for r in results
            if not r.ok and r.error_message
        ]
        agg_err = "；".join(err_msgs) if err_msgs else None

        total_rows = sum(r.row_count_returned for r in results)
        total_ms = sum(r.execution_time_ms for r in results)
        any_trunc = any(r.truncated for r in results)

        head = ""
        if results:
            head = (
                f"共执行 {len(results)} 条 SQL。"
                + (" 全部成功。" if all_ok else f" 存在失败：{agg_err}。")
            )
        body_parts = [r.data_summary_zh for r in results if r.data_summary_zh]
        data_summary_zh = head + " ".join(body_parts)

        out = ExecuteSqlOutput(
            ok=all_ok,
            executed=any_executed,
            error_stage=None if all_ok else "db_execute",
            error_message=None if all_ok else (agg_err or "部分 SQL 未成功"),
            results=results,
            row_count_returned=total_rows,
            truncated=any_trunc,
            data_summary_zh=data_summary_zh,
            execution_time_ms=total_ms,
        )

        return out.model_dump_json(
            indent=2, ensure_ascii=False, exclude_none=True, exclude_defaults=True
        )


def build_execute_sql_tool():
    """装配 ``execute_sql_tool``。连接参数仅来自环境变量。"""
    runner = ExecuteSqlRunner()
    return StructuredTool.from_function(
        func=runner.invoke,
        name="execute_sql_tool",
        description=(
            "在配置好环境变量后连接 MySQL，依次执行 generate_sql JSON 中的 query_sqls。"
            "每条查询写入独立 CSV（UTF-8 无 BOM；单条时文件名为时间戳；多条时为 时间戳_sql1.csv、_sql2.csv…；失败条目仍占对应 sqlN 文件）。"
            "返回 results 列表与聚合摘要。可选环境变量 AGENTIC_BI_SQL_CSV_DIR。"
            "执行前会再次做只读校验；编排上仍建议先调用 check_sql_tool。"
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
        query_sqls=["SELECT sales_month, total_gmv FROM mv_monthly_sales LIMIT 5"],
        result_explanation="演示：取月度 GMV 前 5 行",
    ).model_dump_json(indent=2, ensure_ascii=False)
    print("===== 演示：execute_sql_tool =====")
    print(ExecuteSqlRunner().invoke(demo))
